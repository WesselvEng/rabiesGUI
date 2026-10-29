#!/usr/bin/env python3
"""Browse BIDS subjects and generate/submit per-session RABIES jobs."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import nibabel as nib
from nibabel.filebasedimages import ImageFileError
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DEFAULT_RABIES_IMAGE = ""
DEFAULT_TEMPLATES = ""
PREPROCESS_ARGS = (
    "--anat_template {anat_template} --brain_mask {brain_mask} "
    "--WM_mask {WM_mask} --CSF_mask {CSF_mask} "
    "--vascular_mask {vascular_mask} --TR 1 "
    "--commonspace_reg masking=false,brain_extraction=false,"
    "template_registration=SyN,fast_commonspace=false "
    "--commonspace_resampling 0.3x0.3x0.3"
)
CONFOUND_ARGS = (
    "--TR 1 --highpass 0.01 --smoothing_filter 0.5 --lowpass 0.1 "
    "--nuisance_regressors global_signal mot_6"
)
ANALYSIS_ARGS = (
    "--data_diagnosis --prior_maps {priors} --FC_matrix "
    "--ROI_labels_file {rois} --DR_ICA "
    "--group_ica apply=true,dim=10,random_seed=1 "
    "--prior_bold_idx 0 1 3 5 7 8 9 10 11 15 17 18 "
    "--prior_confound_idx 2 4 6 12 13 14 16 19"
)


def _workflow_path(directory: Path, stage: str) -> Path:
    return directory / f"rabies_{stage}_workflow.pkl"


def _session_result_name(session: str | None) -> str:
    if session in (None, "No session"):
        return "no-session"
    if not session or Path(session).name != session or session in {".", ".."}:
        raise ValueError(f"Invalid BIDS session name: {session!r}")
    return session


def subject_has_previous_results(
    subject: str, results_dir: Path, session: str | None = None
) -> bool:
    subject_results = results_dir / subject
    if session is not None:
        subject_results = subject_results / _session_result_name(session)
    if subject_results.is_dir() and any(subject_results.iterdir()):
        return True
    shared_cleaned = results_dir / "cleaned_timeseries"
    if not shared_cleaned.is_dir():
        return False
    prefix = f"{subject}_"
    if session is None:
        return any(path.name.startswith(prefix) for path in shared_cleaned.iterdir())
    if session == "No session":
        return any(
            path.name.startswith(prefix) and "_ses-" not in path.name
            for path in shared_cleaned.iterdir()
        )
    session_token = f"_{session}_"
    return any(
        path.name.startswith(prefix) and session_token in path.name
        for path in shared_cleaned.iterdir()
    )


def clear_results(results_dir: Path, subjects: list[str] | None = None) -> int:
    """Remove archived result entries without deleting the results directory."""
    results_dir = results_dir.expanduser().resolve()
    project_root = Path(__file__).resolve().parent
    protected_paths = (Path.home().resolve(), project_root)
    if (
        any(results_dir == path or results_dir in path.parents for path in protected_paths)
        or project_root in results_dir.parents
    ):
        raise ValueError(f"Refusing to remove contents of protected directory: {results_dir}")
    if not results_dir.is_dir():
        return 0

    if subjects is None:
        targets = list(results_dir.iterdir())
    else:
        for subject in subjects:
            if not subject or Path(subject).name != subject or subject in {".", ".."}:
                raise ValueError(f"Invalid subject directory name: {subject!r}")
        targets = [results_dir / subject for subject in subjects]

    removed = 0
    for target in targets:
        if target.is_symlink() or target.is_file():
            target.unlink()
            removed += 1
        elif target.is_dir():
            shutil.rmtree(target)
            removed += 1
    return removed


def clear_session_results(
    results_dir: Path, subject: str, sessions: list[str]
) -> int:
    """Remove archived outputs and exported cleaned data for selected sessions."""
    results_dir = results_dir.expanduser().resolve()
    project_root = Path(__file__).resolve().parent
    protected_paths = (Path.home().resolve(), project_root)
    if (
        any(results_dir == path or results_dir in path.parents for path in protected_paths)
        or project_root in results_dir.parents
    ):
        raise ValueError(f"Refusing to remove contents of protected directory: {results_dir}")
    if not subject or Path(subject).name != subject or subject in {".", ".."}:
        raise ValueError(f"Invalid subject directory name: {subject!r}")

    removed = 0
    for session in sessions:
        session_name = _session_result_name(session)
        target = results_dir / subject / session_name
        if target.is_symlink() or target.is_file():
            target.unlink()
            removed += 1
        elif target.is_dir():
            shutil.rmtree(target)
            removed += 1
        cleaned_dir = results_dir / "cleaned_timeseries"
        if cleaned_dir.is_dir():
            token = f"_{session_name}_" if session_name != "no-session" else None
            for path in cleaned_dir.iterdir():
                if path.is_file() and path.name.startswith(f"{subject}_"):
                    if (
                        token in path.name
                        if token is not None
                        else "_ses-" not in path.name
                    ):
                        path.unlink()
                        removed += 1
    return removed


def output_subject_names(output_dir: Path) -> set[str]:
    subject_dirs = ("tmp_bids", "func_preprocess", "func_confound", "func_analysis")
    return {
        entry.name
        for directory_name in subject_dirs
        for parent in [output_dir / directory_name]
        if parent.is_dir() and not parent.is_symlink()
        for entry in parent.iterdir()
        if entry.is_dir()
    }


def clear_output_subjects(output_dir: Path, subjects: list[str] | None = None) -> int:
    """Remove per-subject workflow and staging folders, preserving shared files."""
    output_dir = output_dir.expanduser().resolve()
    project_root = Path(__file__).resolve().parent
    protected_paths = (Path.home().resolve(), project_root)
    if (
        any(output_dir == path or output_dir in path.parents for path in protected_paths)
        or project_root in output_dir.parents
    ):
        raise ValueError(f"Refusing to remove contents of protected directory: {output_dir}")
    if not output_dir.is_dir():
        return 0

    subject_dirs = ("tmp_bids", "func_preprocess", "func_confound", "func_analysis")
    if subjects is None:
        subject_names = output_subject_names(output_dir)
    else:
        for subject in subjects:
            if not subject or Path(subject).name != subject or subject in {".", ".."}:
                raise ValueError(f"Invalid subject directory name: {subject!r}")
        subject_names = set(subjects)

    removed = 0
    for directory_name in subject_dirs:
        parent = output_dir / directory_name
        if not parent.is_dir() or parent.is_symlink():
            continue
        for subject in subject_names:
            target = parent / subject
            if target.is_symlink() or target.is_file():
                target.unlink()
                removed += 1
            elif target.is_dir():
                shutil.rmtree(target)
                removed += 1
    return removed


def stage_status(
    subject: str,
    output_dir: Path,
    results_dir: Path,
    session: str | None = None,
) -> dict[str, bool]:
    """Report completed stages using RABIES' post-run workflow pickle files."""
    subject_output = output_dir / "func_preprocess" / subject
    confound_output = output_dir / "func_confound" / subject
    analysis_output = output_dir / "func_analysis" / subject
    subject_results = results_dir / subject
    if session is not None:
        session_name = _session_result_name(session)
        subject_output /= session_name
        confound_output /= session_name
        analysis_output /= session_name
        subject_results /= session_name

    preprocess_candidates = (
        _workflow_path(subject_output, "preprocess"),
        _workflow_path(subject_results / "preprocess", "preprocess"),
    )
    confound_candidates = (
        _workflow_path(confound_output, "confound_correction"),
        _workflow_path(subject_results / "confound", "confound_correction"),
    )
    analysis_candidates = (
        _workflow_path(analysis_output, "analysis"),
        _workflow_path(subject_results / "analysis", "analysis"),
        _workflow_path(subject_results / "analysis" / subject, "analysis"),
        subject_results / "analysis" / subject / "rabies_analysis.pkl",
    )
    return {
        "preprocess": any(path.is_file() for path in preprocess_candidates),
        "confound": any(path.is_file() for path in confound_candidates),
        "analysis": any(path.is_file() for path in analysis_candidates),
    }


def _validate_subject_prefix(subject_prefix: str) -> str:
    if not subject_prefix or subject_prefix in {".", ".."}:
        raise ValueError("Subject prefix must not be empty, '.' or '..'.")
    if "/" in subject_prefix or "\\" in subject_prefix:
        raise ValueError("Subject prefix must not contain path separators.")
    return subject_prefix


def _contains_subjects(directory: Path, subject_prefix: str) -> bool:
    subject_prefix = _validate_subject_prefix(subject_prefix)
    return any(
        entry.is_dir() and entry.name.startswith(subject_prefix)
        for entry in directory.iterdir()
    )


def discover_subjects(
    bids_dir: Path, subject_prefix: str = "sub-"
) -> list[tuple[str, int, int]]:
    """Return subject IDs and their BOLD/T2w file counts."""
    if not bids_dir.is_dir():
        raise FileNotFoundError(f"BIDS directory does not exist: {bids_dir}")
    subject_prefix = _validate_subject_prefix(subject_prefix)

    subjects = []
    for subject_dir in sorted(bids_dir.iterdir()):
        if not subject_dir.is_dir() or not subject_dir.name.startswith(subject_prefix):
            continue
        bold_count = sum(1 for _ in subject_dir.rglob("*_bold.nii.gz"))
        anat_count = sum(1 for _ in subject_dir.rglob("*_T2w.nii.gz"))
        subjects.append((subject_dir.name, bold_count, anat_count))
    return subjects


def nifti_orientation(path: Path) -> str:
    """Return a NIfTI's axis orientation, or an explicit unreadable status."""
    try:
        image = nib.load(str(path))
    except (ImageFileError, OSError, ValueError) as error:
        return f"Unreadable: {error}"
    return "".join(axis or "?" for axis in nib.aff2axcodes(image.affine))


def session_nifti_orientations(
    subject_dir: Path,
) -> dict[str, list[tuple[Path, str]]]:
    """Return NIfTI orientations grouped by BIDS session."""
    sessions = {
        entry.name: []
        for entry in sorted(subject_dir.iterdir())
        if entry.is_dir() and entry.name.startswith("ses-")
    }
    for path in sorted(subject_dir.rglob("*")):
        if not path.is_file() or not (
            path.name.endswith(".nii") or path.name.endswith(".nii.gz")
        ):
            continue
        relative = path.relative_to(subject_dir)
        session = (
            relative.parts[0]
            if relative.parts and relative.parts[0].startswith("ses-")
            else "No session"
        )
        sessions.setdefault(session, []).append((path, nifti_orientation(path)))
    return sessions


def nifti_orientation_issues(
    bids_dir: Path,
    subjects: list[str],
    selected_sessions: dict[str, set[str]] | None = None,
) -> list[str]:
    """Return selected subjects' missing, unreadable, or non-RAS NIfTIs."""
    issues = []
    for subject in subjects:
        subject_dir = bids_dir / subject
        if not subject_dir.is_dir():
            issues.append(f"{subject}: BIDS subject folder not found.")
            continue
        sessions = session_nifti_orientations(subject_dir)
        if not any(sessions.values()):
            issues.append(f"{subject}: no NIfTI files found.")
        for session, files in sessions.items():
            if (
                selected_sessions is not None
                and session not in selected_sessions.get(subject, set())
            ):
                continue
            for path, orientation in files:
                if orientation != "RAS":
                    session_dir = (
                        subject_dir if session == "No session"
                        else subject_dir / session
                    )
                    relative_path = path.relative_to(session_dir)
                    issues.append(
                        f"{subject}/{session}/{relative_path.as_posix()}: {orientation}"
                    )
    return issues


def reorient_niftis_to_ras(
    bids_dir: Path, subjects: list[str]
) -> tuple[list[Path], Path | None]:
    """Reorient selected subjects' non-RAS NIfTIs, retaining timestamped backups."""
    images: list[tuple[str, Path, nib.spatialimages.SpatialImage]] = []
    issues = []
    for subject in subjects:
        subject_dir = bids_dir / subject
        if not subject_dir.is_dir():
            issues.append(f"{subject}: BIDS subject folder not found.")
            continue
        sessions = session_nifti_orientations(subject_dir)
        if not any(sessions.values()):
            issues.append(f"{subject}: no NIfTI files found.")
        for session, files in sessions.items():
            for path, orientation in files:
                if orientation.startswith("Unreadable:"):
                    issues.append(f"{path}: {orientation}")
                elif orientation != "RAS":
                    try:
                        canonical = nib.as_closest_canonical(nib.load(str(path)))
                    except (ImageFileError, OSError, ValueError) as error:
                        issues.append(f"{path}: {error}")
                        continue
                    if "".join(
                        axis or "?" for axis in nib.aff2axcodes(canonical.affine)
                    ) != "RAS":
                        issues.append(f"{path}: could not be reoriented to RAS.")
                    else:
                        images.append((subject, path, canonical))
    if issues:
        raise ValueError(
            "Cannot reorient NIfTIs until all selected files are readable and "
            "each selected subject contains NIfTI files:\n" + "\n".join(issues)
        )
    if not images:
        return [], None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_root = (
        bids_dir.parent / f"{bids_dir.name}_orientation_backups" / timestamp
    )
    temporary_files: list[tuple[Path, Path]] = []
    try:
        for subject, path, _image in images:
            subject_dir = bids_dir / subject
            backup = backup_root / subject / path.relative_to(subject_dir)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)

        for _subject, path, image in images:
            extension = ".nii.gz" if path.name.endswith(".nii.gz") else ".nii"
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".rabies-reorient-",
                suffix=extension,
                dir=path.parent,
            )
            os.close(descriptor)
            temporary_path = Path(temporary_name)
            temporary_files.append((temporary_path, path))
            nib.save(image, str(temporary_path))
            saved = nib.load(str(temporary_path))
            orientation = "".join(
                axis or "?" for axis in nib.aff2axcodes(saved.affine)
            )
            if orientation != "RAS":
                raise ValueError(
                    f"Reoriented file did not have RAS orientation: {path}"
                )

        for temporary_path, path in temporary_files:
            os.replace(temporary_path, path)
    except (ImageFileError, OSError, ValueError) as error:
        raise OSError(
            f"NIfTI reorientation failed. Original files are backed up in "
            f"{backup_root}: {error}"
        ) from error
    finally:
        for temporary_path, _path in temporary_files:
            temporary_path.unlink(missing_ok=True)

    return [path for _subject, path, _image in images], backup_root


def _nifti_display_label(path: Path, subject_dir: Path, orientation: str) -> str:
    relative = path.relative_to(subject_dir)
    session = (
        relative.parts[0]
        if relative.parts and relative.parts[0].startswith("ses-")
        else None
    )
    modality = next(
        (part for part in relative.parts[:-1] if part in {"anat", "func"}),
        None,
    )
    location = "/".join(part for part in (session, modality) if part)
    if not location:
        location = session or "No session"
    return f"{location} : {orientation}"


def discover_bids_folders(root_dir: Path, subject_prefix: str = "sub-") -> list[Path]:
    """Return immediate child folders containing subject folders with this prefix."""
    if not root_dir.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root_dir}")
    subject_prefix = _validate_subject_prefix(subject_prefix)
    return sorted(
        folder
        for folder in root_dir.iterdir()
        if folder.is_dir()
        and _contains_subjects(folder, subject_prefix)
    )


def move_cleaned_timeseries(subjects: list[str], results_dir: Path) -> tuple[list[Path], list[Path]]:
    """Move selected subjects' cleaned NIfTI files into a shared results folder."""
    destination_dir = results_dir / "cleaned_timeseries"
    moved: list[Path] = []
    skipped: list[Path] = []

    for subject in subjects:
        subject_results = results_dir / subject
        if not subject_results.is_dir():
            continue
        source_dirs = sorted(
            path
            for path in subject_results.rglob("cleaned_timeseries")
            if path.parent.name == "confound_correction_datasink"
        )
        for source_dir in source_dirs:
            for source in sorted(source_dir.rglob("*_cleaned.nii.gz")):
                destination = destination_dir / source.name
                if destination.exists():
                    skipped.append(source)
                    continue
                destination_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                moved.append(destination)

    return moved, skipped


def _shell_command(arguments: list[str]) -> str:
    return shlex.join(arguments)


def _expand_template_paths(arguments: str, templates: dict[str, str]) -> str:
    for name, path in templates.items():
        arguments = arguments.replace(f"{{{name}}}", path)
    return arguments


def _session_name(path: Path, subject: str) -> str | None:
    """Return a file's BIDS session when it is below the subject directory."""
    for parent in path.parents:
        if parent.name == subject:
            relative_path = path.relative_to(parent)
            if relative_path.parts and relative_path.parts[0].startswith("ses-"):
                return relative_path.parts[0]
            return None
    return None


def discover_session_files(
    subject_dir: Path,
) -> dict[str, tuple[list[Path], list[Path]]]:
    """Group BOLD and T2w files by BIDS session for independent jobs."""
    sessions: dict[str, tuple[list[Path], list[Path]]] = {}
    for modality, suffix in (("func", "*_bold.nii.gz"), ("anat", "*_T2w.nii.gz")):
        for path in sorted(subject_dir.rglob(suffix)):
            session = _session_name(path, subject_dir.name) or "No session"
            bold_files, anat_files = sessions.setdefault(session, ([], []))
            (bold_files if modality == "func" else anat_files).append(path)
    return dict(sorted(sessions.items()))


def generate_subject_script(
    subject: str,
    bold_files: list[Path],
    anat_files: list[Path],
    output_dir: Path,
    results_dir: Path,
    templates_dir: Path,
    rabies_image: Path,
    preprocess_args: str = PREPROCESS_ARGS,
    confound_args: str = CONFOUND_ARGS,
    analysis_args: str = ANALYSIS_ARGS,
    session: str | None = None,
) -> str:
    """Build a resumable Bash job for exactly one subject session."""
    if not bold_files:
        raise ValueError(f"No *_bold.nii.gz files found for {subject}.")
    if not anat_files:
        raise ValueError(f"No *_T2w.nii.gz files found for {subject}.")

    file_sessions = {
        _session_name(path, subject)
        for path in (*bold_files, *anat_files)
    }
    if session is None:
        if len(file_sessions) > 1:
            raise ValueError(
                f"Files for {subject} span multiple sessions; generate one script per session."
            )
        selected_session = next(iter(file_sessions))
    else:
        selected_session = None if session == "No session" else session
        if file_sessions != {selected_session}:
            raise ValueError(
                f"Files supplied for {subject} do not all belong to session {session}."
            )
    session_name = _session_result_name(
        selected_session if selected_session is not None else "No session"
    )
    bids = output_dir / "tmp_bids" / subject / session_name
    preprocess = output_dir / "func_preprocess" / subject / session_name
    confound = output_dir / "func_confound" / subject / session_name
    analysis = output_dir / "func_analysis" / subject / session_name
    result_subject = results_dir / subject
    result_session = result_subject / session_name
    preprocess_archive = result_session / "preprocess"
    confound_archive = result_session / "confound"
    analysis_archive = result_session / "analysis"

    templates = {
        "anat_template": "/templates/anatomy/SIGMA_InVivo_Brain_Template.nii.gz",
        "brain_mask": "/templates/anatomy/SIGMA_InVivo_Brain_Mask.nii.gz",
        "WM_mask": "/templates/anatomy/SIGMA_InVivo_WM_bin.nii.gz",
        "CSF_mask": "/templates/anatomy/SIGMA_InVivo_CSF_bin.nii.gz",
        "vascular_mask": "/templates/anatomy/SIGMA_InVivo_CSF_bin.nii.gz",
        "rois": "/templates/atlas/SIGMA_Anatomical_Brain_Atlas.nii.gz",
        "priors": "/templates/canica_resting_state.nii.gz",
    }

    def bind(host_path: Path, container_path: str, read_only: bool = False) -> str:
        suffix = ":ro" if read_only else ""
        return f"{host_path}:{container_path}{suffix}"

    command_base = ["apptainer", "run"]
    preprocess_command = command_base + [
        "-B", bind(bids, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(templates_dir, "/templates", True),
        str(rabies_image), "-f", "-p", "MultiProc", "preprocess",
        "/input_bids/", "/preprocess_outputs/",
    ] + shlex.split(_expand_template_paths(preprocess_args, templates))
    confound_command = command_base + [
        "-B", bind(bids, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(confound, "/confound_correction_outputs"),
        "-B", bind(templates_dir, "/templates", True),
        str(rabies_image), "-f", "confound_correction",
        "/preprocess_outputs/", "/confound_correction_outputs/",
    ] + shlex.split(confound_args)
    analysis_command = command_base + [
        "-B", bind(bids, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(confound, "/confound_correction_outputs"),
        "-B", bind(analysis, "/analysis_outputs"),
        "-B", bind(templates_dir, "/templates", True),
        str(rabies_image), "-f", "-p", "MultiProc", "analysis",
        "/confound_correction_outputs/", "/analysis_outputs/",
    ] + shlex.split(_expand_template_paths(analysis_args, templates))

    lines = [
        "#!/usr/bin/env bash",
        "#SBATCH --time=12:00:00",
        "#SBATCH --mem=8G",
        "#SBATCH --cpus-per-task=2",
        "set -euo pipefail",
        f"subject={shlex.quote(subject)}",
        f"bids={shlex.quote(str(bids))}",
        f"preprocess={shlex.quote(str(preprocess))}",
        f"confound={shlex.quote(str(confound))}",
        f"analysis={shlex.quote(str(analysis))}",
        f"preprocess_archive={shlex.quote(str(preprocess_archive))}",
        f"confound_archive={shlex.quote(str(confound_archive))}",
        f"analysis_archive={shlex.quote(str(analysis_archive))}",
        'mkdir -p "$bids" "$preprocess" "$confound" "$analysis"',
    ]
    for paths, modality in ((bold_files, "func"), (anat_files, "anat")):
        for path in paths:
            session = _session_name(path, subject)
            relative_directory = Path(session) / modality if session else Path(modality)
            bids_directory = bids / relative_directory
            lines.append(f"mkdir -p {shlex.quote(str(bids_directory))}")
            lines.append(
                f"cp -f {shlex.quote(str(path))} {shlex.quote(str(bids_directory))}/"
            )
    preprocess_workflow = _workflow_path(preprocess, "preprocess")
    confound_workflow = _workflow_path(confound, "confound_correction")
    confound_cli = confound / "rabies_confound_correction.pkl"
    analysis_workflow = _workflow_path(analysis, "analysis")
    legacy_analysis_marker = analysis_archive / subject / "rabies_analysis.pkl"
    lines.extend([
        "",
        f"session_name={shlex.quote(session_name)}",
        f"result_session={shlex.quote(str(result_session))}",
        'if [[ -d "$result_session" ]] && [[ -n "$(find "$result_session" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then',
        '  echo "Refusing to analyze $subject session $session_name: previous results exist in $result_session. Clear this session\'s results in the GUI first." >&2',
        "  exit 1",
        "fi",
        f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} ]]; then",
        f"  {_shell_command(preprocess_command)}",
        "fi",
        f"mkdir -p {shlex.quote(str(preprocess_archive))}",
        f"if [[ -f {shlex.quote(str(preprocess_workflow))} ]]; then",
        f"  cp -f {shlex.quote(str(preprocess_workflow))} {shlex.quote(str(preprocess_archive))}/",
        "fi",
        f"if [[ -f {shlex.quote(str(preprocess / 'rabies_preprocess.log'))} ]]; then",
        f"  cp -f {shlex.quote(str(preprocess / 'rabies_preprocess.log'))} {shlex.quote(str(preprocess_archive))}/",
        "fi",
        f"if [[ -d {shlex.quote(str(preprocess / 'preprocess_QC_report'))} && ! -d {shlex.quote(str(preprocess_archive / 'preprocess_QC_report'))} ]]; then",
        f"  cp -a {shlex.quote(str(preprocess / 'preprocess_QC_report'))} {shlex.quote(str(preprocess_archive))}/",
        "fi",
        f"if [[ ! -f {shlex.quote(str(confound_archive / confound_workflow.name))} "
        f"|| ! -f {shlex.quote(str(confound_archive / confound_cli.name))} ]]; then",
        f"  if [[ ! -f {shlex.quote(str(confound_workflow))} "
        f"|| ! -f {shlex.quote(str(confound_cli))} ]]; then",
        f"    {_shell_command(confound_command)}",
        "  fi",
        f"  mkdir -p {shlex.quote(str(confound_archive))}",
        f"  cp -a {shlex.quote(str(confound / 'confound_correction_datasink'))} {shlex.quote(str(confound_archive))}/",
        f"  cp -f {shlex.quote(str(confound_workflow))} {shlex.quote(str(confound_archive))}/",
        f"  cp -f {shlex.quote(str(confound_cli))} {shlex.quote(str(confound_archive))}/",
        f"  cp -f {shlex.quote(str(confound / 'rabies_confound_correction.log'))} {shlex.quote(str(confound_archive))}/",
        "fi",
        f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
        f"&& -f {shlex.quote(str(confound_archive / confound_workflow.name))} "
        f"&& -f {shlex.quote(str(confound_archive / confound_cli.name))} "
        f"&& ! -f {shlex.quote(str(analysis_archive / analysis_workflow.name))} ]]; then",
        f"  cp -a {shlex.quote(str(confound_archive / 'confound_correction_datasink'))} \"$confound/\"",
        f"  cp -f {shlex.quote(str(confound_archive / confound_workflow.name))} \"$confound/\"",
        f"  cp -f {shlex.quote(str(confound_archive / confound_cli.name))} \"$confound/\"",
        "fi",
        f"if [[ ! -f {shlex.quote(str(analysis_archive / analysis_workflow.name))} "
        f"&& ! -f {shlex.quote(str(legacy_analysis_marker))} ]]; then",
        f"  if [[ ! -f {shlex.quote(str(analysis_workflow))} ]]; then",
        f"    {_shell_command(analysis_command)}",
        "  fi",
        f"  mkdir -p {shlex.quote(str(analysis_archive))}",
        f"  cp -a \"$analysis/\". {shlex.quote(str(analysis_archive))}/",
        "  find \"$analysis\" -mindepth 1 -delete",
        "fi",
        "if [[ -d \"$confound\" ]]; then find \"$confound\" -mindepth 1 -delete; fi",
    ])
    if selected_session is not None:
        session_directory = bids / selected_session
        session_archive = result_session
        lines.extend([
            f"mkdir -p {shlex.quote(str(session_archive))}",
            f"cp -a {shlex.quote(str(session_directory))}/. "
            f"{shlex.quote(str(session_archive))}/",
        ])
    else:
        lines.extend([
            f"mkdir -p {shlex.quote(str(result_session))}",
            f"cp -a {shlex.quote(str(bids / 'func'))} "
            f"{shlex.quote(str(result_session))}/",
            f"cp -a {shlex.quote(str(bids / 'anat'))} "
            f"{shlex.quote(str(result_session))}/",
        ])
    lines.extend(['echo "Finished subject $subject"', ""])
    return "\n".join(lines)


class ProjectSetupWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RABIES Project Setup")
        self.resize(820, 430)
        self.setMinimumSize(720, 380)
        self.path_fields: dict[str, QLineEdit] = {}
        self.subject_manager: SubjectManager | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.addWidget(QLabel(
            "Choose the project folders and template set, then continue to the subject manager."
        ))

        paths = QWidget()
        path_layout = QFormLayout(paths)
        defaults = (
            ("Project root", "root", ""),
            ("Output directory", "output", ""),
            ("Results directory", "results", ""),
            ("Template folder (rat, mouse, or custom)", "templates", DEFAULT_TEMPLATES),
            ("RABIES image", "image", DEFAULT_RABIES_IMAGE),
            ("Subject folder prefix", "subject_prefix", "sub-"),
        )
        for label, key, value in defaults:
            field = QLineEdit(value)
            self.path_fields[key] = field
            if key == "subject_prefix":
                field.textChanged.connect(self._populate_bids_folders)
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(field)
            if key != "subject_prefix":
                browse = QPushButton("Browse…")
                browse.clicked.connect(lambda _checked=False, item=key: self._browse(item))
                row_layout.addWidget(browse)
            path_layout.addRow(label, row_widget)

        self.bids_folders = QComboBox()
        self.bids_folders.addItem("Select a folder containing sub-* subjects", None)
        bids_widget = QWidget()
        bids_layout = QHBoxLayout(bids_widget)
        bids_layout.setContentsMargins(0, 0, 0, 0)
        bids_layout.addWidget(self.bids_folders)
        browse_bids = QPushButton("Browse…")
        browse_bids.clicked.connect(self._browse_bids_folder)
        bids_layout.addWidget(browse_bids)
        path_layout.addRow("Original BIDS folder (og_folder)", bids_widget)
        layout.addWidget(paths)
        layout.addWidget(QLabel(
            "For mouse or custom templates, check that the RABIES stage arguments "
            "match the files in the selected template folder."
        ))

        controls = QHBoxLayout()
        controls.addStretch()
        open_manager = QPushButton("Open subject manager")
        open_manager.clicked.connect(self.open_subject_manager)
        controls.addWidget(open_manager)
        layout.addLayout(controls)
        self.status = QLabel("Select a project root and original BIDS folder.")
        layout.addWidget(self.status)
        self.path_fields["root"].textChanged.connect(self._populate_bids_folders)
        self.path_fields["root"].editingFinished.connect(self._update_project_output_defaults)

    def _browse(self, key: str) -> None:
        if key == "image":
            selected, _ = QFileDialog.getOpenFileName(self, "Select RABIES image")
        else:
            current_value = self.path_fields[key].text()
            current_path = Path(current_value).expanduser() if current_value else Path.home()
            dialog_title = "Select project root" if key == "root" else "Select directory"
            selected = QFileDialog.getExistingDirectory(self, dialog_title, str(current_path))
        if selected:
            self.path_fields[key].setText(selected)
            if key == "root":
                self._populate_bids_folders()
                self._update_project_output_defaults()

    def _browse_bids_folder(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Select original BIDS folder",
            self.path_fields["root"].text().strip() or str(Path.home()),
        )
        if not selected:
            return
        selected_path = Path(selected)
        try:
            subject_prefix = _validate_subject_prefix(
                self.path_fields["subject_prefix"].text().strip()
            )
        except ValueError as error:
            QMessageBox.critical(self, "Invalid subject prefix", str(error))
            return
        try:
            has_subjects = _contains_subjects(selected_path, subject_prefix)
        except OSError as error:
            QMessageBox.critical(self, "Could not read BIDS folder", str(error))
            return
        if not has_subjects:
            QMessageBox.critical(
                self, "No BIDS subjects found",
                f"No {subject_prefix}* subject folders were found in {selected_path}.",
            )
            return
        for index in range(self.bids_folders.count()):
            if self.bids_folders.itemData(index) == str(selected_path):
                self.bids_folders.setCurrentIndex(index)
                return
        self.bids_folders.addItem(selected_path.name, str(selected_path))
        self.bids_folders.setCurrentIndex(self.bids_folders.count() - 1)

    def _populate_bids_folders(self) -> None:
        root_value = self.path_fields["root"].text().strip()
        previously_selected = self.bids_folders.currentData()
        self.bids_folders.clear()
        prefix = self.path_fields["subject_prefix"].text().strip()
        self.bids_folders.addItem(
            f"Select a folder containing {prefix or '<prefix>'}* subjects", None
        )
        if not root_value:
            return
        try:
            subject_prefix = _validate_subject_prefix(prefix)
            folders = discover_bids_folders(
                Path(root_value).expanduser(), subject_prefix
            )
        except (OSError, ValueError) as error:
            self.status.setText(str(error))
            return
        if not folders:
            if (
                previously_selected
                and Path(previously_selected).is_dir()
                and _contains_subjects(Path(previously_selected), subject_prefix)
            ):
                self.bids_folders.addItem(
                    Path(previously_selected).name, previously_selected
                )
                self.bids_folders.setCurrentIndex(self.bids_folders.count() - 1)
                return
            self.status.setText(
                f"No direct subfolders containing {subject_prefix}* subjects were found in {root_value}."
            )
            return
        for folder in folders:
            self.bids_folders.addItem(folder.name, str(folder))
            if str(folder) == previously_selected:
                self.bids_folders.setCurrentIndex(self.bids_folders.count() - 1)
        if (
            previously_selected
            and Path(previously_selected).is_dir()
            and all(str(folder) != previously_selected for folder in folders)
            and _contains_subjects(Path(previously_selected), subject_prefix)
        ):
            self.bids_folders.addItem(
                Path(previously_selected).name, previously_selected
            )
            self.bids_folders.setCurrentIndex(self.bids_folders.count() - 1)

    def _selected_bids_dir(self) -> Path | None:
        selected = self.bids_folders.currentData()
        return Path(selected) if selected else None

    def _update_project_output_defaults(self) -> None:
        root_value = self.path_fields["root"].text().strip()
        if not root_value:
            return
        root = Path(root_value).expanduser()
        self.path_fields["output"].setText(str(root / "rabies_output"))
        self.path_fields["results"].setText(str(root / "rabies_results"))

    def _project_paths(self) -> tuple[Path, Path, Path, Path, Path]:
        root_value = self.path_fields["root"].text().strip()
        return (
            Path(root_value).expanduser() if root_value else Path(),
            Path(self.path_fields["output"].text()).expanduser(),
            Path(self.path_fields["results"].text()).expanduser(),
            Path(self.path_fields["templates"].text()).expanduser(),
            Path(self.path_fields["image"].text()).expanduser(),
        )

    def open_subject_manager(self) -> None:
        root, output, results, _, _ = self._project_paths()
        bids_dir = self._selected_bids_dir()
        if not root.is_dir():
            QMessageBox.critical(self, "Project root not found", f"Select an existing project root: {root}")
            return
        if bids_dir is None or not bids_dir.is_dir():
            QMessageBox.critical(
                self, "Original BIDS folder not set",
                "Choose or browse to an existing original BIDS folder.",
            )
            return
        try:
            subject_prefix = _validate_subject_prefix(
                self.path_fields["subject_prefix"].text().strip()
            )
        except ValueError as error:
            QMessageBox.critical(self, "Invalid subject prefix", str(error))
            return
        if not self.path_fields["output"].text().strip() or not self.path_fields["results"].text().strip():
            QMessageBox.critical(
                self, "Output paths not set",
                "Set both the output and results directories before continuing.",
            )
            return
        try:
            discover_subjects(bids_dir, subject_prefix)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not read BIDS subjects", str(error))
            return

        if self.subject_manager is None:
            self.subject_manager = SubjectManager(self)
        else:
            self.subject_manager.refresh_subjects()
            self.subject_manager.update_project_label()
        self.hide()
        self.subject_manager.show()
        self.subject_manager.raise_()
        self.subject_manager.activateWindow()


class SubjectManager(QMainWindow):
    def __init__(self, setup_window: ProjectSetupWindow) -> None:
        super().__init__()
        self.setup_window = setup_window
        self.path_fields = setup_window.path_fields
        self.bids_folders = setup_window.bids_folders
        self.setWindowTitle("RABIES Subject/Session Manager")
        self.resize(1180, 900)
        self.setMinimumSize(900, 740)
        self.stage_args = {
            "Preprocessing": PREPROCESS_ARGS,
            "Confound correction": CONFOUND_ARGS,
            "Analysis": ANALYSIS_ARGS,
        }
        self._build_ui()
        self.update_project_label()
        self.refresh_subjects()

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        project_options = QHBoxLayout()
        self.project_label = QLabel()
        project_options.addWidget(self.project_label, 1)
        project_settings = QPushButton("Project setup…")
        project_settings.clicked.connect(self.show_project_setup)
        project_options.addWidget(project_settings)
        layout.addLayout(project_options)

        self.subjects = QTableWidget(0, 6)
        self.subjects.setHorizontalHeaderLabels(
            ["Subject", "BOLD scans", "T2w scans", "Preprocess", "Confound", "Analysis"]
        )
        self.subjects.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.subjects.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.subjects.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.subjects.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.subjects.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.subjects.currentCellChanged.connect(self._show_session_details)
        layout.addWidget(self.subjects, 2)

        self.session_details_label = QLabel("Session details: select a subject.")
        layout.addWidget(self.session_details_label)
        self.session_details = QTableWidget(0, 6)
        self.session_details.setHorizontalHeaderLabels([
            "Session",
            "NIfTI orientations",
            "Session archive",
            "Session preprocess",
            "Session confound",
            "Session analysis",
        ])
        self.session_details.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.session_details.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.session_details.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.session_details.setWordWrap(True)
        self.session_details.setStyleSheet(
            "QToolTip { background-color: #ffffdc; color: #000000; "
            "border: 1px solid #767676; padding: 2px; }"
        )
        self.session_details.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.session_details.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        layout.addWidget(self.session_details, 1)

        options = QHBoxLayout()
        for label, callback in (
            ("Refresh subjects", self.refresh_subjects),
            ("Select all", self.select_all),
            ("Clear selection", self.clear_selection),
            ("Remove selected scripts", self.remove_scripts),
            ("Move cleaned timeseries", self.move_selected_cleaned_timeseries),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            options.addWidget(button)
        options.addStretch()
        for label, callback in (
            ("RABIES arguments…", self.edit_arguments),
            ("Create scripts", self.create_scripts),
            ("Reorient selected NIfTIs to RAS", self.reorient_selected_niftis),
            ("Submit scripts with sbatch", self.submit_scripts),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            options.addWidget(button)
        layout.addLayout(options)

        cleanup_options = QHBoxLayout()
        cleanup_options.addWidget(QLabel("Archived results (permanent deletion):"))
        for label, callback in (
            ("Clear selected results", self.clear_selected_results),
            ("Clear selected session results", self.clear_selected_session_results),
            ("Clear ALL results", self.clear_all_results),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            cleanup_options.addWidget(button)
        cleanup_options.addWidget(QLabel("Temporary workflow output:"))
        for label, callback in (
            ("Clear selected output", self.clear_selected_output),
            ("Clear ALL subject output", self.clear_all_output),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            cleanup_options.addWidget(button)
        cleanup_options.addStretch()
        layout.addLayout(cleanup_options)

        self.status = QLabel(
            "Create or submit independent RABIES jobs for selected subject sessions."
        )
        layout.addWidget(self.status)

    def _project_paths(self) -> tuple[Path, Path, Path, Path, Path]:
        return self.setup_window._project_paths()

    def _selected_bids_dir(self) -> Path | None:
        return self.setup_window._selected_bids_dir()

    def update_project_label(self) -> None:
        root, output, results, templates, image = self._project_paths()
        bids = self._selected_bids_dir()
        self.project_label.setText(
            f"Project: {root}  |  BIDS: {bids or 'not selected'}  |  "
            f"Templates: {templates}  |  Output: {output}  |  Results: {results}  |  "
            f"RABIES: {image}"
        )

    def show_project_setup(self) -> None:
        self.hide()
        self.setup_window.show()
        self.setup_window.raise_()
        self.setup_window.activateWindow()

    def refresh_subjects(self) -> None:
        if not self.path_fields["root"].text().strip():
            self.status.setText("Browse to the project root, then select the original BIDS folder.")
            return
        bids_dir = self._selected_bids_dir()
        if bids_dir is None:
            prefix = self.path_fields["subject_prefix"].text().strip() or "<prefix>"
            self.status.setText(
                f"Select the original BIDS folder containing {prefix}* subjects."
            )
            return
        if not self.path_fields["output"].text().strip() or not self.path_fields["results"].text().strip():
            self.status.setText("Choose a project root or enter output and results directories.")
            return
        try:
            _, output, results, _, _ = self._project_paths()
            subject_prefix = _validate_subject_prefix(
                self.path_fields["subject_prefix"].text().strip()
            )
            discovered = discover_subjects(bids_dir, subject_prefix)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not read subjects", str(error))
            return

        was_blocked = self.subjects.blockSignals(True)
        try:
            self.subjects.setRowCount(len(discovered))
            for row, (subject, bold_count, anat_count) in enumerate(discovered):
                session_files = discover_session_files(bids_dir / subject)
                session_states = [
                    stage_status(subject, output, results, session)
                    for session in session_files
                ]
                states = {
                    stage: [session[stage] for session in session_states]
                    for stage in ("preprocess", "confound", "analysis")
                }
                previous_results = any(
                    subject_has_previous_results(subject, results, session)
                    for session in session_files
                )

                def status_text(values: list[bool]) -> str:
                    if values and all(values):
                        return "Complete"
                    if any(values):
                        return "Partial"
                    return "Not found"

                values = (
                    subject,
                    str(bold_count),
                    str(anat_count),
                    status_text(states["preprocess"]),
                    status_text(states["confound"]),
                    "Existing output (clear to rerun)" if previous_results else (
                        status_text(states["analysis"])
                    ),
                )
                for column, value in enumerate(values):
                    self.subjects.setItem(
                        row,
                        column,
                        QTableWidgetItem(value),
                    )
        finally:
            self.subjects.blockSignals(was_blocked)
        self.session_details.setRowCount(0)
        self.session_details_label.setText("Session details: select a subject.")
        self.status.setText(f"Found {len(discovered)} subject(s) in {bids_dir}.")

    def _show_session_details(
        self, current_row: int, _current_column: int,
        _previous_row: int, _previous_column: int,
    ) -> None:
        subject_item = self.subjects.item(current_row, 0)
        bids_dir = self._selected_bids_dir()
        if subject_item is None or bids_dir is None:
            self.session_details.setRowCount(0)
            self.session_details_label.setText("Session details: select a subject.")
            return

        subject = subject_item.text()
        _, output, results, _, _ = self._project_paths()
        try:
            sessions = session_nifti_orientations(bids_dir / subject)
        except OSError as error:
            QMessageBox.critical(self, "Could not read session files", str(error))
            return
        if not sessions:
            sessions = {"No session": []}
        session_states = {
            session: stage_status(subject, output, results, session)
            for session in sessions
        }
        rows = [
            (session, path, orientation)
            for session, files in sessions.items()
            for path, orientation in files
        ]
        if not rows:
            rows = [(session, None, "No NIfTI files found") for session in sessions]
        self.session_details.setRowCount(len(rows))
        for row, (session, path, orientation) in enumerate(rows):
            result_session = results / subject / _session_result_name(session)
            archive = "Present" if result_session.is_dir() else "Not found"
            states = session_states[session]
            values = (
                session,
                (
                    _nifti_display_label(path, bids_dir / subject, orientation)
                    if path is not None
                    else orientation
                ),
                archive,
                "Complete" if states["preprocess"] else "Not found",
                "Complete" if states["confound"] else "Not found",
                "Complete" if states["analysis"] else "Not found",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1 and path is not None:
                    item.setToolTip(str(path.resolve()))
                self.session_details.setItem(row, column, item)
        self.session_details_label.setText(
            f"Sessions for {subject} (stage results are session-specific):"
        )

    def select_all(self) -> None:
        self.subjects.selectAll()

    def clear_selection(self) -> None:
        self.subjects.clearSelection()

    def _selected_subjects(self) -> list[str]:
        return [
            item.text()
            for item in self.subjects.selectedItems()
            if item.column() == 0
        ]

    def edit_arguments(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("RABIES stage arguments")
        dialog.resize(780, 560)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(
            "Enter stage options as command-line arguments, without the stage name "
            "or input/output paths. Use the RABIES CLI help as a reference."
        ))

        tabs = QTabWidget()
        editors: dict[str, QPlainTextEdit] = {}
        for stage, arguments in self.stage_args.items():
            editor = QPlainTextEdit(arguments)
            editor.setTabStopDistance(32)
            editors[stage] = editor
            tabs.addTab(editor, stage)
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.stage_args = {
                stage: editor.toPlainText().strip()
                for stage, editor in editors.items()
            }
            self.status.setText("RABIES arguments updated for future script generation.")

    def remove_scripts(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(self, "No subjects selected", "Select subjects whose scripts you want to remove.")
            return
        _, output, _, _, _ = self._project_paths()
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(self, "Output directory not set", "Choose a project root or set an output directory.")
            return

        script_dir = output / "tmp_script"
        existing_paths = [
            path
            for subject in selected
            for path in (
                *script_dir.glob(f"scrip_{subject}_*.sh"),
                script_dir / f"scrip_{subject}.sh",
            )
            if path.is_file()
        ]
        if not existing_paths:
            QMessageBox.information(self, "No scripts found", "No generated scripts exist for the selected subjects.")
            return
        answer = QMessageBox.question(
            self,
            "Remove generated scripts",
            f"Remove {len(existing_paths)} selected script(s)? This does not remove RABIES outputs.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            for path in existing_paths:
                path.unlink()
        except OSError as error:
            QMessageBox.critical(self, "Could not remove scripts", str(error))
            return
        self.status.setText(f"Removed {len(existing_paths)} generated script(s).")

    def clear_selected_results(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(
                self, "No subjects selected",
                "Select the subjects whose archived results you want to remove.",
            )
            return
        self._clear_results(selected)

    def clear_selected_session_results(self) -> None:
        subject_item = self.subjects.item(self.subjects.currentRow(), 0)
        sessions = sorted({
            item.text()
            for item in self.session_details.selectedItems()
            if item.column() == 0
        })
        if subject_item is None or not sessions:
            QMessageBox.information(
                self,
                "No sessions selected",
                "Select one or more session rows in the session details table.",
            )
            return
        _, _, results, _, _ = self._project_paths()
        results_value = self.path_fields["results"].text().strip()
        if not results_value:
            QMessageBox.critical(
                self, "Results directory not set",
                "Choose a project root or set a results directory.",
            )
            return
        subject = subject_item.text()
        answer = QMessageBox.question(
            self,
            "Clear selected session results",
            f"Permanently delete archived outputs and moved cleaned timeseries "
            f"for {subject} ({', '.join(sessions)}) from {results}?\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_session_results(results, subject, sessions)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self, "Could not clear session results", str(error)
            )
            return
        self.refresh_subjects()
        self.status.setText(
            f"Removed {removed} archived session result item(s) for {subject}."
        )

    def clear_all_results(self) -> None:
        self._clear_results(None)

    def _clear_results(self, subjects: list[str] | None) -> None:
        results_value = self.path_fields["results"].text().strip()
        if not results_value:
            QMessageBox.critical(
                self, "Results directory not set",
                "Choose a project root or set a results directory.",
            )
            return
        results = Path(results_value).expanduser()
        if subjects is not None:
            targets = [results / subject for subject in subjects]
        else:
            targets = list(results.iterdir()) if results.is_dir() else []
        existing = [path for path in targets if path.exists() or path.is_symlink()]
        if not existing:
            QMessageBox.information(
                self, "No archived results",
                f"No archived results were found in {results}.",
            )
            return

        if subjects is None:
            title = "Clear all archived results"
            scope = f"all {len(existing)} item(s) in {results}"
        else:
            title = "Clear selected subjects' results"
            scope = f"archived results for {len(existing)} selected subject(s) in {results}"
        answer = QMessageBox.question(
            self,
            title,
            f"Permanently delete {scope}?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_results(results, subjects)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not clear archived results", str(error))
            return
        self.refresh_subjects()
        self.status.setText(f"Removed {removed} archived result item(s) from {results}.")

    def clear_selected_output(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(
                self, "No subjects selected",
                "Select the subjects whose temporary workflow output you want to remove.",
            )
            return
        self._clear_output(selected)

    def clear_all_output(self) -> None:
        self._clear_output(None)

    def _clear_output(self, subjects: list[str] | None) -> None:
        output_value = self.path_fields["output"].text().strip()
        if not output_value:
            QMessageBox.critical(
                self, "Output directory not set",
                "Choose a project root or set an output directory.",
            )
            return
        output = Path(output_value).expanduser()
        if subjects is None:
            subject_names = output_subject_names(output)
            scope = f"all temporary outputs for {len(subject_names)} subject(s)"
        else:
            subject_names = set(subjects)
            scope = f"temporary outputs for {len(subjects)} selected subject(s)"
        if not subject_names:
            QMessageBox.information(
                self, "No temporary subject output",
                f"No per-subject workflow output was found in {output}.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Clear subject workflow output",
            f"Permanently delete {scope} from {output}?\n"
            "This removes temporary BIDS copies and preprocessing, confound, and "
            "analysis folders, but preserves shared files and generated scripts. "
            "Archived results are not removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_output_subjects(output, sorted(subject_names))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not clear workflow output", str(error))
            return
        self.refresh_subjects()
        self.status.setText(
            f"Removed {removed} subject-specific output folder(s) from {output}."
        )

    def move_selected_cleaned_timeseries(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(
                self, "No subjects selected",
                "Select the subjects whose cleaned timeseries you want to move.",
            )
            return
        _, _, results, _, _ = self._project_paths()
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(self, "Results directory not set", "Choose a project root or set a results directory.")
            return

        destination_dir = results / "cleaned_timeseries"
        answer = QMessageBox.question(
            self,
            "Move cleaned timeseries",
            f"Move cleaned NIfTI files for {len(selected)} selected subject(s) into\n"
            f"{destination_dir}?\nExisting files with the same name will be skipped.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved, skipped = move_cleaned_timeseries(selected, results)
        except OSError as error:
            QMessageBox.critical(self, "Could not move cleaned timeseries", str(error))
            return

        self.status.setText(
            f"Moved {len(moved)} cleaned timeseries; skipped {len(skipped)} name collision(s)."
        )
        message = (
            f"Moved {len(moved)} file(s) to {destination_dir}."
            f"\nSkipped {len(skipped)} file(s) because the destination filename already exists."
        )
        QMessageBox.information(self, "Cleaned timeseries", message)

    def reorient_selected_niftis(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(
                self, "No subjects selected",
                "Select the subjects whose NIfTI files you want to reorient.",
            )
            return
        bids_dir = self._selected_bids_dir()
        if bids_dir is None or not bids_dir.is_dir():
            QMessageBox.critical(
                self, "Original BIDS folder not set",
                "Select an existing original BIDS folder before reorienting files.",
            )
            return

        candidates = []
        unreadable = []
        try:
            for subject in selected:
                for files in session_nifti_orientations(bids_dir / subject).values():
                    for path, orientation in files:
                        if orientation.startswith("Unreadable:"):
                            unreadable.append(f"{path}: {orientation}")
                        elif orientation != "RAS":
                            candidates.append((path, orientation))
        except OSError as error:
            QMessageBox.critical(self, "Could not read NIfTI files", str(error))
            return
        if unreadable:
            QMessageBox.critical(
                self, "Cannot reorient unreadable NIfTIs",
                "The following files could not be read:\n" + "\n".join(unreadable),
            )
            return
        if not candidates:
            QMessageBox.information(
                self, "NIfTIs already in RAS",
                "No non-RAS NIfTI files were found for the selected subjects.",
            )
            return

        file_list = "\n".join(
            f"{path} ({orientation})" for path, orientation in candidates
        )
        confirmation = QMessageBox.question(
            self,
            "Reorient NIfTIs to RAS",
            f"This will replace {len(candidates)} non-RAS NIfTI file(s) in the "
            "BIDS dataset. Original files will be backed up outside the dataset "
            "in a timestamped orientation-backups folder.\n\n"
            f"{file_list}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        try:
            reoriented, backup_root = reorient_niftis_to_ras(bids_dir, selected)
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not reorient NIfTI files", str(error))
            return
        if backup_root is None:
            QMessageBox.information(
                self, "NIfTIs already in RAS",
                "No non-RAS NIfTI files needed reorientation.",
            )
            return
        self.refresh_subjects()
        for row in range(self.subjects.rowCount()):
            item = self.subjects.item(row, 0)
            if item is not None and item.text() in selected:
                self.subjects.selectRow(row)
        first_row = next(
            (
                row
                for row in range(self.subjects.rowCount())
                if self.subjects.item(row, 0) is not None
                and self.subjects.item(row, 0).text() == selected[0]
            ),
            -1,
        )
        if first_row >= 0:
            self.subjects.setCurrentCell(first_row, 0)
        self.status.setText(
            f"Reoriented {len(reoriented)} NIfTI file(s) to RAS. "
            f"Originals backed up in {backup_root}."
        )
        QMessageBox.information(
            self,
            "NIfTIs reoriented",
            f"Reoriented {len(reoriented)} NIfTI file(s) to RAS.\n"
            f"Originals backed up in:\n{backup_root}",
        )

    def create_scripts(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(self, "No subjects selected", "Select at least one subject first.")
            return
        bids_dir = self._selected_bids_dir()
        if bids_dir is None:
            QMessageBox.critical(
                self, "Original BIDS folder not set",
                "Select the original BIDS folder (og_folder) containing the sub-* folders.",
            )
            return
        _, output, results, templates, image = self._project_paths()
        if not bids_dir.is_dir():
            QMessageBox.critical(
                self, "Original BIDS folder not found",
                f"Select an existing original BIDS folder (og_folder): {bids_dir}",
            )
            return
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(self, "Output directory not set", "Select a project root or set an output directory.")
            return
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(self, "Results directory not set", "Select a project root or set a results directory.")
            return
        if not templates.is_dir():
            QMessageBox.critical(self, "Templates not found", f"Template directory does not exist: {templates}")
            return
        if not image.is_file():
            QMessageBox.critical(self, "RABIES image not found", f"Apptainer image does not exist: {image}")
            return
        script_dir = output / "tmp_script"
        try:
            script_dir.mkdir(parents=True, exist_ok=True)
            scripts = []
            for subject in selected:
                subject_dir = bids_dir / subject
                for session, (bold_files, anat_files) in discover_session_files(
                    subject_dir
                ).items():
                    script = generate_subject_script(
                        subject,
                        bold_files,
                        anat_files,
                        output,
                        results,
                        templates,
                        image,
                        preprocess_args=self.stage_args["Preprocessing"],
                        confound_args=self.stage_args["Confound correction"],
                        analysis_args=self.stage_args["Analysis"],
                        session=session,
                    )
                    session_name = _session_result_name(session)
                    scripts.append((
                        script_dir / f"scrip_{subject}_{session_name}.sh",
                        script,
                    ))
            for script_path, script in scripts:
                script_path.write_text(script, encoding="utf-8")
                script_path.chmod(0o755)
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not create scripts", str(error))
            return
        self.status.setText(
            f"Created {len(scripts)} session script(s) for "
            f"{len(selected)} subject(s) in {script_dir}."
        )
        QMessageBox.information(
            self, "Session scripts created",
            f"Created {len(scripts)} session script(s) for {len(selected)} subject(s).",
        )

    def submit_scripts(self) -> None:
        selected = self._selected_subjects()
        selected_session_names = sorted({
            item.text()
            for item in self.session_details.selectedItems()
            if item.column() == 0
        })
        current_subject_item = self.subjects.item(self.subjects.currentRow(), 0)
        if selected_session_names and current_subject_item is not None:
            selected = [current_subject_item.text()]
        if not selected:
            QMessageBox.information(self, "No subjects selected", "Select at least one subject first.")
            return
        _, output, results, _, _ = self._project_paths()
        bids_dir = self._selected_bids_dir()
        if bids_dir is None or not bids_dir.is_dir():
            QMessageBox.critical(
                self, "Original BIDS folder not set",
                "Select an existing original BIDS folder before submitting jobs.",
            )
            return
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(self, "Output directory not set", "Select a project root or set an output directory.")
            return
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(self, "Results directory not set", "Select a project root or set a results directory.")
            return
        session_filter = (
            {selected[0]: set(selected_session_names)}
            if selected_session_names
            else None
        )
        try:
            orientation_issues = nifti_orientation_issues(
                bids_dir, selected, session_filter
            )
        except OSError as error:
            QMessageBox.critical(self, "Could not check NIfTI orientations", str(error))
            return
        if orientation_issues:
            QMessageBox.critical(
                self,
                "NIfTI orientation check failed",
                "Jobs cannot be submitted unless every BIDS NIfTI is readable and in RAS orientation. "
                "Scripts may still be created for inspection.\n\n"
                + "\n".join(orientation_issues),
            )
            return
        script_paths = []
        blocked_sessions = []
        missing = []
        for subject in selected:
            subject_sessions = discover_session_files(bids_dir / subject)
            session_names = (
                selected_session_names
                if session_filter is not None
                else subject_sessions
            )
            for session in session_names:
                if session not in subject_sessions:
                    missing.append(f"{subject}/{session}: no session files found")
                    continue
                session_name = _session_result_name(session)
                script_path = (
                    output / "tmp_script"
                    / f"scrip_{subject}_{session_name}.sh"
                )
                if subject_has_previous_results(subject, results, session):
                    blocked_sessions.append(f"{subject}/{session}")
                elif script_path.is_file():
                    script_paths.append(script_path)
                else:
                    missing.append(str(script_path))
        if not script_paths and blocked_sessions:
            QMessageBox.critical(
                self,
                "Session results must be cleared",
                "No session jobs can be submitted because archived results already "
                "exist for the selected sessions:\n"
                + "\n".join(blocked_sessions)
                + "\nSelect those sessions and choose Clear selected session results to rerun them.",
            )
            return
        if not script_paths and not blocked_sessions and not missing:
            QMessageBox.critical(
                self, "No session jobs found",
                "No BOLD/T2w session inputs were found for the selected subjects.",
            )
            return
        if missing:
            QMessageBox.critical(
                self,
                "Session scripts not found",
                "Create scripts for the selected sessions first:\n" + "\n".join(missing),
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Submit session jobs",
            f"Submit {len(script_paths)} session job(s) to SLURM with sbatch?"
            + (
                "\nExisting results will cause these sessions to be skipped:\n"
                + "\n".join(blocked_sessions)
                if blocked_sessions
                else ""
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        submitted = []
        try:
            for path in script_paths:
                result = subprocess.run(
                    ["sbatch", str(path)], check=True, capture_output=True, text=True
                )
                submitted.append(result.stdout.strip() or str(path))
        except (OSError, subprocess.CalledProcessError) as error:
            details = getattr(error, "stderr", None) or str(error)
            QMessageBox.critical(
                self,
                "Submission failed",
                f"Submitted {len(submitted)} job(s) before the error.\n{details}",
            )
            return
        skipped_text = (
            f" Skipped {len(blocked_sessions)} session(s) with existing results."
            if blocked_sessions
            else ""
        )
        self.status.setText(
            f"Submitted {len(submitted)} session job(s) with sbatch.{skipped_text}"
        )
        QMessageBox.information(
            self, "Session jobs submitted", "\n".join(submitted) + skipped_text
        )


if __name__ == "__main__":
    app = QApplication([])
    window = ProjectSetupWindow()
    window.show()
    app.exec()
