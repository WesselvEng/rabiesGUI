#!/usr/bin/env python3
"""Shared GUI and per-session RABIES/FIXRABIES workflows."""

from __future__ import annotations

import filecmp
import logging
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

import nibabel as nib
from nibabel.filebasedimages import ImageFileError
from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplashScreen,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


DEFAULT_RABIES_IMAGE = ""
DEFAULT_TEMPLATES = ""
SPLASH_IMAGE = Path(__file__).with_name("RABIES-RABIES.png")
NORMAL_PIPELINE_VARIANTS = (
    ("Preprocessing only", "preproc_only"),
    ("Preprocessing + confound correction", "preproc_confound"),
    ("Analysis only (from confound cleaned timeseries)", "analysis_only"),
    ("Whole pipeline", "whole_pipeline"),
)
FIX_PIPELINE_VARIANTS = (
    ("Preprocessing + FIXRABIES prepare", "fixrabies_prepare"),
    ("FIXRABIES prepare only", "fixrabies_prepare_only"),
)
PIPELINE_VARIANTS = NORMAL_PIPELINE_VARIANTS + FIX_PIPELINE_VARIANTS
COHORT_PIPELINE_VARIANTS = PIPELINE_VARIANTS
FIXRABIES_SPECIES = ("ratSIGMA", "mouseDSURQE", "mouseAIBS")
COHORT_ANALYSIS_ARCHIVE_DIRS = (
    "commonspace_analysis_datasink",
    "data_diagnosis_datasink",
)
FIX_DIRECTORY_PREFIX = "fixrabies_"
FIX_SUBJECTS_FILE = ".rabies_gui_subjects.txt"
FIX_SPECIES_FILE = ".rabies_gui_species.txt"
FIX_CREATE_NEW = "__create_new__"
SINGLE_SUBJECT_OUTPUT_DIR = "single-subject"
TEMPLATE_FILE_DEFAULTS = {
    "anat_template": "anatomy/SIGMA_InVivo_Brain_Template.nii.gz",
    "brain_mask": "anatomy/SIGMA_InVivo_Brain_Mask.nii.gz",
    "WM_mask": "anatomy/SIGMA_InVivo_WM_bin.nii.gz",
    "CSF_mask": "anatomy/SIGMA_InVivo_CSF_bin.nii.gz",
    "vascular_mask": "anatomy/SIGMA_InVivo_CSF_bin.nii.gz",
    "rois": "atlas/SIGMA_Anatomical_Brain_Atlas.nii.gz",
    "priors": "canica_resting_state.nii.gz",
}
TEMPLATE_FILE_LABELS = {
    "anat_template": "Anatomical template",
    "brain_mask": "Brain mask",
    "WM_mask": "White-matter mask",
    "CSF_mask": "CSF mask",
    "vascular_mask": "Vascular mask",
    "rois": "ROI labels",
    "priors": "Prior maps",
}
logger = logging.getLogger("rabies_gui")
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
    "--prior_bold_idx 0 1 3 5 7 8 9 10 11 15 17 18 19"
    "--prior_confound_idx 2 4 6 12 13 14 16"
)

DARK_STYLE = """
QWidget {
    background-color: #202124;
    color: #e8eaed;
    selection-background-color: #4c8bf5;
    selection-color: #ffffff;
}
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {
    background-color: #292a2d;
    border: 1px solid #5f6368;
    border-radius: 4px;
    padding: 5px;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #8ab4f8;
}
QPushButton, QToolButton {
    background-color: #34363a;
    border: 1px solid #5f6368;
    border-radius: 4px;
    padding: 6px 10px;
}
QPushButton:hover, QToolButton:hover {
    background-color: #45484d;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: #2b4d7e;
}
QPushButton:disabled, QToolButton:disabled {
    color: #80868b;
    background-color: #292a2d;
}
QTableWidget, QTableView, QTreeView, QListView {
    background-color: #202124;
    alternate-background-color: #292a2d;
    gridline-color: #3c4043;
    border: 1px solid #3c4043;
}
QHeaderView::section {
    background-color: #303134;
    color: #e8eaed;
    border: 1px solid #3c4043;
    padding: 5px;
}
QTabWidget::pane {
    border: 1px solid #5f6368;
}
QTabBar::tab {
    background-color: #303134;
    border: 1px solid #5f6368;
    padding: 6px 10px;
}
QTabBar::tab:selected {
    background-color: #45484d;
}
QMenu, QMenuBar {
    background-color: #292a2d;
    color: #e8eaed;
}
QMenu::item:selected {
    background-color: #3c4043;
}
QToolTip {
    background-color: #ffffdc;
    color: #000000;
    border: 1px solid #767676;
    padding: 2px;
}
QScrollBar:vertical {
    background: #202124;
    width: 12px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #5f6368;
    min-height: 24px;
    border-radius: 5px;
}
QScrollBar:horizontal {
    background: #202124;
    height: 12px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: #5f6368;
    min-width: 24px;
    border-radius: 5px;
}
QScrollBar::add-line, QScrollBar::sub-line {
    width: 0;
    height: 0;
}
"""


def configure_dark_mode(application: QApplication) -> None:
    """Apply a consistent dark palette and Fusion styling to the GUI."""
    application.setStyle("Fusion")
    palette = application.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202124"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#292a2d"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#303134"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffdc"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#000000"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#34363a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e8eaed"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#4c8bf5"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#8ab4f8"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa0a6"))
    application.setPalette(palette)
    application.setStyleSheet(DARK_STYLE)


def _workflow_path(directory: Path, stage: str) -> Path:
    return directory / f"rabies_{stage}_workflow.pkl"


SUBJECT_ARCHIVE_DIRECTORIES = (
    "tmp_bids_session",
    "func_preprocess",
    "func_confound",
    "func_analysis",
)


def _subject_archive_stage(
    results_dir: Path, stage_directory: str, subject: str, session: str
) -> Path:
    return (
        results_dir / SINGLE_SUBJECT_OUTPUT_DIR
        / stage_directory / subject / _session_result_name(session)
    )


def _session_result_name(session: str | None) -> str:
    if session in (None, "No session"):
        return "no-session"
    if not session or Path(session).name != session or session in {".", ".."}:
        raise ValueError(f"Invalid BIDS session name: {session!r}")
    return session


def subject_has_previous_results(
    subject: str, results_dir: Path, session: str | None = None
) -> bool:
    if session is not None:
        session_name = _session_result_name(session)
        if any(
            (stage_path := _subject_archive_stage(
                results_dir, stage, subject, session_name
            )).is_dir()
            and any(stage_path.iterdir())
            for stage in SUBJECT_ARCHIVE_DIRECTORIES
        ):
            return True
        legacy_session = results_dir / subject / session_name
        if legacy_session.is_dir() and any(legacy_session.iterdir()):
            return True
    elif any(
        (stage_path := results_dir / SINGLE_SUBJECT_OUTPUT_DIR / stage / subject).is_dir()
        and any(stage_path.iterdir())
        for stage in SUBJECT_ARCHIVE_DIRECTORIES
    ):
        return True
    legacy_subject = results_dir / subject
    if session is None and legacy_subject.is_dir() and any(legacy_subject.iterdir()):
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


def list_fix_directories(project_root: Path) -> list[Path]:
    """Find project-level FIXRABIES directories created by this manager."""
    if not project_root.is_dir():
        return []
    return sorted(
        path
        for path in project_root.iterdir()
        if path.is_dir()
        and not path.is_symlink()
        and (
            (path / FIX_SUBJECTS_FILE).is_file()
            or (path / FIX_SPECIES_FILE).is_file()
            or (
                path.name.startswith(FIX_DIRECTORY_PREFIX)
                and (path / "data").is_dir()
            )
        )
    )


def fix_directory_has_subject(
    fix_dir: Path, subject: str, session: str | None = None
) -> bool:
    """Check assignments and prepared scan IDs for a subject in a FIX directory."""
    assignments = fix_dir / FIX_SUBJECTS_FILE
    if session is None and assignments.is_file():
        if subject in {
            line.strip()
            for line in assignments.read_text(encoding="utf-8").splitlines()
        }:
            return True

    data_dir = fix_dir / "data"
    if not data_dir.is_dir():
        return False
    for scan_dir in data_dir.iterdir():
        if not scan_dir.is_dir() or not (
            scan_dir.name == subject or scan_dir.name.startswith(f"{subject}_")
        ):
            continue
        if session is None:
            return True
        if session == "No session":
            if "_ses-" not in scan_dir.name:
                return True
        elif f"_{session}_" in scan_dir.name or scan_dir.name.endswith(f"_{session}"):
            return True
    return False


def fix_directories_for_subject(
    project_root: Path, subject: str
) -> list[Path]:
    """Return all project FIX directories containing or assigned to a subject."""
    return [
        fix_dir
        for fix_dir in list_fix_directories(project_root)
        if fix_directory_has_subject(fix_dir, subject)
    ]


def fix_directory_has_prepared_scan(
    fix_dir: Path, subject: str, session: str
) -> bool:
    """Check whether a FIX directory already has prepared scans for a session."""
    data_dir = fix_dir / "data"
    if not data_dir.is_dir():
        return False
    for scan_dir in data_dir.iterdir():
        if not scan_dir.is_dir() or not (
            scan_dir.name == subject or scan_dir.name.startswith(f"{subject}_")
        ):
            continue
        if session == "No session":
            if "_ses-" not in scan_dir.name:
                return True
        elif f"_{session}_" in scan_dir.name or scan_dir.name.endswith(f"_{session}"):
            return True
    return False


def suggested_fix_directory(project_root: Path) -> Path:
    """Return an unused project-level FIX directory path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    candidate = project_root / f"{FIX_DIRECTORY_PREFIX}{timestamp}"
    suffix = 1
    while candidate.exists():
        candidate = project_root / f"{FIX_DIRECTORY_PREFIX}{timestamp}_{suffix}"
        suffix += 1
    return candidate


def _validate_fix_directory_name(name: str) -> str:
    """Validate a manually entered FIX folder name as one path component."""
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or Path(name).name != name
        or any(character in name for character in '<>:"|?*')
        or name.endswith((" ", "."))
    ):
        raise ValueError(
            "FIX folder name must be a valid single folder name, without path "
            "separators or reserved characters."
        )
    return name


def record_fix_subjects(
    fix_dir: Path, subjects: list[str], species: str
) -> None:
    """Persist pending and completed subject assignments in a FIX directory."""
    species_file = fix_dir / FIX_SPECIES_FILE
    if species_file.is_file():
        existing_species = species_file.read_text(encoding="utf-8").strip()
        if existing_species != species:
            raise ValueError(
                f"FIXRABIES folder {fix_dir} uses {existing_species!r}, "
                f"not the selected species {species!r}."
            )
    else:
        species_file.write_text(species + "\n", encoding="utf-8")
    manifest = fix_dir / FIX_SUBJECTS_FILE
    existing = (
        manifest.read_text(encoding="utf-8").splitlines()
        if manifest.is_file()
        else []
    )
    manifest.write_text(
        "\n".join(sorted(set(existing).union(subjects))) + "\n",
        encoding="utf-8",
    )


def fix_directory_from_script(script_path: Path) -> Path | None:
    """Read the shared FIX directory embedded in a generated script."""
    for line in script_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("fix_dir="):
            assignment = shlex.split(line)
            if assignment:
                return Path(assignment[0].partition("=")[2])
    return None


def pipeline_has_previous_results(
    subject: str,
    results_dir: Path,
    session: str,
    pipeline: str,
    fix_dir: Path | None = None,
) -> bool:
    session_name = _session_result_name(session)
    stage_directories = {
        "preprocess": "func_preprocess",
        "confound": "func_confound",
        "analysis": "func_analysis",
        "fixrabies": "fixrabies",
    }
    completed_stages = {
        "preproc_only": ("preprocess", "confound", "analysis"),
        "preproc_confound": ("confound", "analysis"),
        "analysis_only": ("analysis",),
        "whole_pipeline": ("analysis",),
        "fixrabies_prepare": ("fixrabies",),
        "fixrabies_prepare_only": ("fixrabies",),
    }[pipeline]
    if any(
        (
            (stage_results := _subject_archive_stage(
                results_dir, stage_directories[stage], subject, session_name
            )).is_dir()
            and any(stage_results.iterdir())
        )
        or (
            (legacy_stage := results_dir / subject / session_name / stage).is_dir()
            and any(legacy_stage.iterdir())
        )
        for stage in completed_stages
    ):
        return True
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"} and fix_dir is not None:
        return fix_directory_has_prepared_scan(fix_dir, subject, session)
    if pipeline != "whole_pipeline":
        return False
    shared_cleaned = results_dir / "cleaned_timeseries"
    if not shared_cleaned.is_dir():
        return False
    prefix = f"{subject}_"
    if session == "No session":
        return any(
            path.name.startswith(prefix) and "_ses-" not in path.name
            for path in shared_cleaned.iterdir()
        )
    return any(
        path.name.startswith(prefix) and f"_{session}_" in path.name
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
        targets = [
            results_dir / subject
            for subject in subjects
        ] + [
            results_dir / SINGLE_SUBJECT_OUTPUT_DIR / stage / subject
            for stage in SUBJECT_ARCHIVE_DIRECTORIES
            for subject in subjects
        ]

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
        targets = [
            _subject_archive_stage(results_dir, stage, subject, session_name)
            for stage in SUBJECT_ARCHIVE_DIRECTORIES
        ]
        targets.append(results_dir / subject / session_name)
        for target in targets:
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
    output_dir = output_dir / SINGLE_SUBJECT_OUTPUT_DIR
    if output_dir.is_symlink():
        return set()
    subject_dirs = (
        "tmp_bids",
        "tmp_bids_session",
        "func_preprocess",
        "func_confound",
        "func_analysis",
    )
    return {
        entry.name
        for directory_name in subject_dirs
        for parent in [output_dir / directory_name]
        if parent.is_dir() and not parent.is_symlink()
        for entry in parent.iterdir()
        if entry.is_dir()
        and not entry.is_symlink()
        and any(entry.iterdir())
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
    output_root = output_dir
    output_dir = output_root / SINGLE_SUBJECT_OUTPUT_DIR
    if output_dir.is_symlink():
        raise ValueError(
            f"Refusing to clear symlinked workflow output directory: {output_dir}"
        )
    if not output_dir.is_dir():
        return 0

    subject_dirs = (
        "tmp_bids",
        "tmp_bids_session",
        "func_preprocess",
        "func_confound",
        "func_analysis",
    )
    if subjects is None:
        subject_names = output_subject_names(output_root)
    else:
        for subject in subjects:
            if not subject or Path(subject).name != subject or subject in {".", ".."}:
                raise ValueError(f"Invalid subject directory name: {subject!r}")
        subject_names = set(subjects)

    removed = 0
    staging_dirs = {"tmp_bids", "tmp_bids_session"}
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
                if directory_name in staging_dirs:
                    for child in target.iterdir():
                        if child.is_symlink() or child.is_file():
                            child.unlink()
                        elif child.is_dir():
                            shutil.rmtree(child)
                else:
                    shutil.rmtree(target)
                removed += 1
    return removed


def stage_status(
    subject: str,
    output_dir: Path,
    results_dir: Path,
    session: str | None = None,
    project_root: Path | None = None,
) -> dict[str, bool]:
    """Report completed RABIES stages and FIXRABIES prepared scan output."""
    output_dir = output_dir / SINGLE_SUBJECT_OUTPUT_DIR
    subject_output = output_dir / "func_preprocess" / subject
    confound_output = output_dir / "func_confound" / subject
    analysis_output = output_dir / "func_analysis" / subject
    archive_root = results_dir / SINGLE_SUBJECT_OUTPUT_DIR
    legacy_subject_results = results_dir / subject
    if session is not None:
        session_name = _session_result_name(session)
        subject_output /= session_name
        confound_output /= session_name
        analysis_output /= session_name
        legacy_subject_results /= session_name

    archive_session = (
        _session_result_name(session) if session is not None else None
    )
    preprocess_archive = archive_root / "func_preprocess" / subject
    confound_archive = archive_root / "func_confound" / subject
    analysis_archive = archive_root / "func_analysis" / subject
    if archive_session is not None:
        preprocess_archive /= archive_session
        confound_archive /= archive_session
        analysis_archive /= archive_session
    preprocess_candidates = (
        _workflow_path(subject_output, "preprocess"),
        _workflow_path(preprocess_archive, "preprocess"),
        _workflow_path(legacy_subject_results / "preprocess", "preprocess"),
    )
    confound_candidates = (
        _workflow_path(confound_output, "confound_correction"),
        _workflow_path(confound_archive, "confound_correction"),
        _workflow_path(
            legacy_subject_results / "confound", "confound_correction"
        ),
    )
    analysis_candidates = (
        _workflow_path(analysis_output, "analysis"),
        _workflow_path(analysis_archive, "analysis"),
        _workflow_path(legacy_subject_results / "analysis", "analysis"),
        _workflow_path(
            legacy_subject_results / "analysis" / subject, "analysis"
        ),
        legacy_subject_results / "analysis" / subject / "rabies_analysis.pkl",
    )
    fix_session = session if session is not None else "No session"
    fix_complete = project_root is not None and any(
        fix_directory_has_prepared_scan(fix_dir, subject, fix_session)
        for fix_dir in list_fix_directories(project_root)
    )
    return {
        "preprocess": any(path.is_file() for path in preprocess_candidates),
        "confound": any(path.is_file() for path in confound_candidates),
        "analysis": any(path.is_file() for path in analysis_candidates),
        "fixrabies": fix_complete,
    }


def _validate_subject_prefix(subject_prefix: str) -> str:
    if not subject_prefix or subject_prefix in {".", ".."}:
        raise ValueError("Subject prefix must not be empty, '.' or '..'.")
    if "/" in subject_prefix or "\\" in subject_prefix:
        raise ValueError("Subject prefix must not contain path separators.")
    return subject_prefix


def _is_mrs_path(path: Path, subject_dir: Path) -> bool:
    """Return whether a path is inside a BIDS MRS modality folder."""
    return any(
        part.casefold() == "mrs"
        for part in path.relative_to(subject_dir).parts[:-1]
    )


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
        bold_count = sum(
            1
            for path in subject_dir.rglob("*_bold.nii.gz")
            if not _is_mrs_path(path, subject_dir)
        )
        anat_count = sum(
            1
            for path in subject_dir.rglob("*_T2w.nii.gz")
            if not _is_mrs_path(path, subject_dir)
        )
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
        if not path.is_file() or _is_mrs_path(path, subject_dir):
            continue
        if not (
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


def move_cleaned_timeseries(
    subjects: list[str],
    results_dir: Path,
    output_dir: Path | None = None,
    cohort_mode: bool = False,
) -> tuple[list[Path], list[Path]]:
    """Move selected cleaned NIfTIs, removing identical duplicate source copies."""
    destination_dir = results_dir / "cleaned_timeseries"
    moved: list[Path] = []
    removed_duplicates: list[Path] = []

    if cohort_mode:
        if output_dir is None:
            raise ValueError("The output directory is required in cohort mode.")
        cleaned_directories = (
            output_dir
            / "cohort"
            / "confound"
            / "confound_correction_datasink"
            / "cleaned_timeseries",
            results_dir
            / "cohort"
            / "confound"
            / "confound_correction_datasink"
            / "cleaned_timeseries",
        )
        selected_subjects = set(subjects)
        source_files = sorted(
            source
            for cleaned_dir in cleaned_directories
            if cleaned_dir.is_dir()
            for source in cleaned_dir.rglob("*_cleaned.nii.gz")
            if source.name.split("_", 1)[0] in selected_subjects
        )
    else:
        source_files = []
        for subject in subjects:
            subject_results = (
                results_dir
                / SINGLE_SUBJECT_OUTPUT_DIR
                / "func_confound"
                / subject,
                results_dir / subject,
            )
            source_files.extend(
                source
                for subject_root in subject_results
                if subject_root.is_dir()
                for source_dir in subject_root.rglob("cleaned_timeseries")
                if source_dir.parent.name == "confound_correction_datasink"
                for source in source_dir.rglob("*_cleaned.nii.gz")
            )
        source_files.sort()

    sources_by_name: dict[str, list[Path]] = {}
    for source in source_files:
        sources_by_name.setdefault(source.name, []).append(source)

    for name, sources in sources_by_name.items():
        destination = destination_dir / name
        if destination.exists() and not destination.is_file():
            raise ValueError(
                f"Cleaned-timeseries destination is not a file: {destination}"
            )
        candidates = ([destination] if destination.is_file() else []) + sources
        reference = candidates[0]
        conflicting = [
            candidate
            for candidate in candidates[1:]
            if not filecmp.cmp(reference, candidate, shallow=False)
        ]
        if conflicting:
            paths = ", ".join(str(path) for path in candidates)
            raise ValueError(
                f"Different cleaned timeseries share the filename {name!r}; "
                f"no files were moved. Resolve the conflicting files: {paths}"
            )

    for name, sources in sources_by_name.items():
        destination = destination_dir / name
        if destination.is_file():
            duplicates = sources
        else:
            destination_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(sources[0]), str(destination))
            moved.append(destination)
            duplicates = sources[1:]
        for duplicate in duplicates:
            duplicate.unlink()
            removed_duplicates.append(duplicate)

    return moved, removed_duplicates


def _shell_command(arguments: list[str]) -> str:
    return shlex.join(arguments)


def _log_generated_script(script_path: Path, script: str) -> None:
    logger.info("Generated script: %s\n%s", script_path, script)


def _expand_template_paths(arguments: str, templates: dict[str, str]) -> str:
    for name, path in templates.items():
        arguments = arguments.replace(f"{{{name}}}", path)
    return arguments


def _resolve_template_files(
    template_files: Mapping[str, str | Path] | None,
) -> tuple[dict[str, str], list[str]]:
    templates = {
        name: f"/templates/{relative_path}"
        for name, relative_path in TEMPLATE_FILE_DEFAULTS.items()
    }
    binds: list[str] = []
    for name, selected_path in (template_files or {}).items():
        if name not in TEMPLATE_FILE_DEFAULTS:
            raise ValueError(f"Unknown template file variable: {name}")
        host_path = Path(selected_path).expanduser()
        if not host_path.is_file():
            raise ValueError(f"Template file does not exist: {host_path}")
        host_path = host_path.resolve()
        extension = "".join(host_path.suffixes)
        container_path = f"/tmp/rabies_gui_custom_{name}{extension}"
        templates[name] = container_path
        binds.extend(["-B", f"{host_path}:{container_path}:ro"])
    return templates, binds


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
            if _is_mrs_path(path, subject_dir):
                continue
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
    pipeline: str = "whole_pipeline",
    fix_species: str = "ratSIGMA",
    fix_dir: Path | None = None,
    archive_outputs: bool = True,
    template_files: Mapping[str, str | Path] | None = None,
) -> str:
    """Build a resumable Bash job for exactly one subject session."""
    if not bold_files:
        raise ValueError(f"No *_bold.nii.gz files found for {subject}.")
    if not anat_files:
        raise ValueError(f"No *_T2w.nii.gz files found for {subject}.")
    if pipeline not in {variant for _, variant in PIPELINE_VARIANTS}:
        raise ValueError(f"Unknown pipeline variant: {pipeline}")
    if fix_species not in FIXRABIES_SPECIES:
        raise ValueError(f"Unsupported FIXRABIES species: {fix_species}")
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"} and fix_dir is None:
        raise ValueError("A shared project-level FIXRABIES directory is required.")

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
    output_dir = output_dir / SINGLE_SUBJECT_OUTPUT_DIR
    bids = output_dir / "tmp_bids_session" / subject / session_name
    preprocess = output_dir / "func_preprocess" / subject / session_name
    confound = output_dir / "func_confound" / subject / session_name
    analysis = output_dir / "func_analysis" / subject / session_name
    subject_archive_root = results_dir / SINGLE_SUBJECT_OUTPUT_DIR
    session_archive = (
        subject_archive_root / "tmp_bids_session" / subject / session_name
    )
    preprocess_archive = (
        subject_archive_root / "func_preprocess" / subject / session_name
    )
    confound_archive = (
        subject_archive_root / "func_confound" / subject / session_name
    )
    analysis_archive = (
        subject_archive_root / "func_analysis" / subject / session_name
    )
    legacy_session_archive = results_dir / subject / session_name
    if pipeline == "analysis_only" and archive_outputs:
        legacy_archives = (
            ("preprocess", preprocess_archive, legacy_session_archive / "preprocess"),
            ("confound_correction", confound_archive, legacy_session_archive / "confound"),
        )
        for stage, archive_path, legacy_path in legacy_archives:
            if (
                not _workflow_path(archive_path, stage).is_file()
                and _workflow_path(legacy_path, stage).is_file()
            ):
                if stage == "preprocess":
                    preprocess_archive = legacy_path
                elif stage == "confound_correction":
                    confound_archive = legacy_path
        if not session_archive.is_dir() and (
            legacy_session_archive / "input_bids"
        ).is_dir():
            session_archive = legacy_session_archive / "input_bids"
    templates, template_binds = _resolve_template_files(template_files)

    def bind(host_path: Path, container_path: str, read_only: bool = False) -> str:
        suffix = ":ro" if read_only else ""
        return f"{host_path}:{container_path}{suffix}"

    command_base = ["apptainer", "run"]
    preprocess_command = command_base + [
        "-B", bind(bids, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "-p", "MultiProc", "--local_threads", "4",
        "preprocess",
        "/input_bids/", "/preprocess_outputs/",
    ] + shlex.split(_expand_template_paths(preprocess_args, templates))
    confound_command = command_base + [
        "-B", bind(bids, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(confound, "/confound_correction_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "confound_correction",
        "/preprocess_outputs/", "/confound_correction_outputs/",
    ] + shlex.split(confound_args)
    analysis_confound_source = (
        confound_archive if pipeline == "analysis_only" and archive_outputs
        else confound
    )
    analysis_bids_source = (
        session_archive if pipeline == "analysis_only" and archive_outputs
        else bids
    )
    analysis_preprocess_source = (
        preprocess_archive
        if pipeline == "analysis_only" and archive_outputs
        else preprocess
    )
    analysis_command = command_base + [
        "-B", bind(
            analysis_bids_source,
            "/input_bids",
            pipeline == "analysis_only" and archive_outputs,
        ),
        "-B", bind(
            analysis_preprocess_source,
            "/preprocess_outputs",
            pipeline == "analysis_only" and archive_outputs,
        ),
        "-B", bind(
            analysis_confound_source,
            "/confound_correction_outputs",
            pipeline == "analysis_only" and archive_outputs,
        ),
        "-B", bind(analysis, "/analysis_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "-p", "MultiProc", "analysis",
        "/confound_correction_outputs/", "/analysis_outputs/",
    ] + shlex.split(_expand_template_paths(analysis_args, templates))
    fix_prepare_command: str | None = None
    fix_marker = None
    fix_scan_check = None
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
        assert fix_dir is not None
        fix_prepare_command = " ".join([
            "fixrabies",
            "prepare",
            "-preprocess_dir",
            '"$preprocess"',
            "-fix_dir",
            shlex.quote(str(fix_dir)),
            "-species",
            shlex.quote(fix_species),
            "-nipype",
            shlex.quote('{"plugin":"MultiProc","n_procs":4}'),
        ])
        fix_marker = fix_dir / ".rabies_gui_prepared" / f"{subject}_{session_name}.done"
        scan_prefix = (
            subject if session_name == "no-session"
            else f"{subject}_{session_name}"
        )
        find_names = (
            f"-name {shlex.quote(scan_prefix)} "
            f"-o -name {shlex.quote(scan_prefix + '_*')}"
        )
        no_session_filter = (
            " ! -name '*_ses-*'" if session_name == "no-session" else ""
        )
        fix_scan_check = (
            f'[[ -d {shlex.quote(str(fix_dir / "data"))} && '
            f'-n "$(find {shlex.quote(str(fix_dir / "data"))} '
            f'-mindepth 1 -maxdepth 1 -type d \\( {find_names} \\)'
            f'{no_session_filter} -print -quit)" ]]'
        )

    lines = [
        "#!/usr/bin/env bash",
        "#SBATCH --time=12:00:00",
        f"#SBATCH --mem={'4G' if pipeline == 'fixrabies_prepare_only' else '8G'}",
        "#SBATCH --cpus-per-task=4",
        "set -euo pipefail",
        f"subject={shlex.quote(subject)}",
        f"session_name={shlex.quote(session_name)}",
        f"bids={shlex.quote(str(bids))}",
        f"bids_parent={shlex.quote(str(bids.parent))}",
        f"preprocess={shlex.quote(str(preprocess))}",
        f"preprocess_output={shlex.quote(str(preprocess))}",
        f"confound={shlex.quote(str(confound))}",
        f"analysis={shlex.quote(str(analysis))}",
        *(
            [f"fix_dir={shlex.quote(str(fix_dir))}"]
            if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}
            and fix_dir is not None
            else []
        ),
        f"session_archive={shlex.quote(str(session_archive))}",
        f"preprocess_archive={shlex.quote(str(preprocess_archive))}",
        f"confound_archive={shlex.quote(str(confound_archive))}",
        f"analysis_archive={shlex.quote(str(analysis_archive))}",
    ]
    if pipeline != "fixrabies_prepare_only" and (
        pipeline != "analysis_only" or not archive_outputs
    ):
        lines.extend([
            'mkdir -p "$bids_parent" "$preprocess"',
            'bids_staging=$(mktemp -d "$bids_parent/.${session_name}.XXXXXX")',
            'trap \'if [[ -n "${bids_staging:-}" && -d "$bids_staging" ]]; then rm -rf -- "$bids_staging"; fi\' EXIT',
        ])
        for paths, modality in ((bold_files, "func"), (anat_files, "anat")):
            for path in paths:
                lines.append(f'mkdir -p "$bids_staging/{modality}"')
                lines.append(
                    f"cp -f {shlex.quote(str(path))} \"$bids_staging/{modality}/\""
                )
        lines.extend([
            'if [[ -L "$bids" ]]; then',
            '  echo "Refusing to replace symlinked session input directory: $bids" >&2',
            "  exit 1",
            "fi",
            'if [[ -e "$bids" ]]; then rm -rf -- "$bids"; fi',
            'mv "$bids_staging" "$bids"',
            'bids_staging=""',
        ])
    preprocess_workflow = _workflow_path(preprocess, "preprocess")
    archived_preprocess_workflow = _workflow_path(
        preprocess_archive, "preprocess"
    )
    confound_workflow = _workflow_path(confound, "confound_correction")
    confound_cli = confound / "rabies_confound_correction.pkl"
    analysis_workflow = _workflow_path(analysis, "analysis")
    legacy_analysis_marker = (
        legacy_session_archive / "analysis" / subject / "rabies_analysis.pkl"
    )
    if pipeline in {"whole_pipeline", "analysis_only"}:
        lines.extend([
            *(
                [
                    f"if [[ -d {shlex.quote(str(analysis_archive))} "
                    f"&& -n \"$(find {shlex.quote(str(analysis_archive))} -mindepth 1 -maxdepth 1 -print -quit)\" ]]; then",
                    '  echo "Refusing to analyze $subject session $session_name: previous analysis results exist. Clear this session\'s results in the GUI first." >&2',
                    "  exit 1",
                    "fi",
                ]
                if archive_outputs
                else []
            ),
        ])
    if pipeline == "fixrabies_prepare_only":
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} "
            f"&& -f {shlex.quote(str(archived_preprocess_workflow))} ]]; then",
            f"  preprocess={shlex.quote(str(preprocess_archive))}",
            "fi",
            *(
                [
                    f"if [[ \"$preprocess\" != {shlex.quote(str(preprocess_archive))} ]]; then",
                    f"  mkdir -p {shlex.quote(str(preprocess_archive))}",
                    f"  echo \"Archiving preprocessing output to {preprocess_archive}\"",
                    f"  cp -av \"$preprocess/\". {shlex.quote(str(preprocess_archive))}/",
                    "fi",
                ]
                if archive_outputs
                else []
            ),
        ])
    if pipeline == "fixrabies_prepare_only":
        lines.extend([
            'if [[ ! -f "$preprocess/rabies_preprocess_workflow.pkl" ]]; then',
            '  echo "Preprocessing output is missing for $subject session $session_name: $preprocess" >&2',
            "  exit 1",
            "fi",
        ])
    elif pipeline != "analysis_only":
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} ]]; then",
            f"  {_shell_command(preprocess_command)}",
            "fi",
            *(
                [
                    f"mkdir -p {shlex.quote(str(preprocess_archive))}",
                    f"if [[ -f {shlex.quote(str(preprocess_workflow))} ]]; then",
                    f"  cp -f {shlex.quote(str(preprocess_workflow))} {shlex.quote(str(preprocess_archive))}/",
                    "fi",
                    f"if [[ -d {shlex.quote(str(preprocess))} ]]; then",
                    f"  echo \"Archiving preprocessing output to {preprocess_archive}\"",
                    f"  cp -av {shlex.quote(str(preprocess))}/. {shlex.quote(str(preprocess_archive))}/",
                    "fi",
                ]
                if archive_outputs
                else []
            ),
        ])
    if pipeline in {"preproc_confound", "whole_pipeline"}:
        lines.extend([
            'mkdir -p "$confound"',
            *(
                [
                    f"if [[ ! -f {shlex.quote(str(confound_archive / confound_workflow.name))} "
                    f"|| ! -f {shlex.quote(str(confound_archive / confound_cli.name))} ]]; then",
                    f"  if [[ ! -f {shlex.quote(str(confound_workflow))} "
                    f"|| ! -f {shlex.quote(str(confound_cli))} ]]; then",
                    f"    {_shell_command(confound_command)}",
                    "  fi",
                    f"  mkdir -p {shlex.quote(str(confound_archive))}",
                    f"  echo \"Archiving confound output to {confound_archive}\"",
                    f"  cp -av {shlex.quote(str(confound))}/. {shlex.quote(str(confound_archive))}/",
                    "fi",
                ]
                if archive_outputs
                else [
                    f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
                    f"|| ! -f {shlex.quote(str(confound_cli))} ]]; then",
                    f"  {_shell_command(confound_command)}",
                    "fi",
                ]
            ),
        ])
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
        assert fix_dir is not None
        assert fix_marker is not None
        assert fix_prepare_command is not None
        assert fix_scan_check is not None
        lines.extend([
            f"mkdir -p {shlex.quote(str(fix_dir / '.rabies_gui_prepared'))}",
            f"if [[ ! -f {shlex.quote(str(fix_marker))} ]] || ! {fix_scan_check}; then",
            '  if ! command -v flock >/dev/null 2>&1; then',
            '    echo "flock is required to safely prepare scans into a shared FIXRABIES directory." >&2',
            "    exit 127",
            "  fi",
            "  (",
            "    flock -x 9",
            f"    if [[ ! -f {shlex.quote(str(fix_marker))} ]] || ! {fix_scan_check}; then",
            '      if ! command -v fixrabies >/dev/null 2>&1; then',
            '        echo "FIXRABIES CLI (fixrabies) is not available on PATH in this job environment." >&2',
            "        exit 127",
            "      fi",
            f"      if {fix_scan_check}; then",
            '        echo "FIXRABIES data for this subject/session already exists without a completion marker; inspect the scan output before retrying." >&2',
            "        exit 1",
            "      fi",
            f"      {fix_prepare_command}",
            f"      touch {shlex.quote(str(fix_marker))}",
            "    fi",
            f"  ) 9>{shlex.quote(str(fix_dir / '.rabies_gui_prepare.lock'))}",
            "fi",
        ])
    if pipeline == "analysis_only":
        if not archive_outputs:
            lines.extend([
                f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} "
                f"&& -f {shlex.quote(str(archived_preprocess_workflow))} ]]; then",
                f"  mkdir -p {shlex.quote(str(preprocess))}",
                f"  cp -a {shlex.quote(str(preprocess_archive))}/. {shlex.quote(str(preprocess))}/",
                "fi",
                f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
                f"&& -f {shlex.quote(str(confound_archive / confound_workflow.name))} ]]; then",
                f"  mkdir -p {shlex.quote(str(confound))}",
                f"  cp -a {shlex.quote(str(confound_archive))}/. {shlex.quote(str(confound))}/",
                "fi",
            ])
        analysis_preprocess_workflow = (
            archived_preprocess_workflow if archive_outputs else preprocess_workflow
        )
        analysis_confound_workflow = (
            confound_archive / confound_workflow.name
            if archive_outputs else confound_workflow
        )
        analysis_bids_source = session_archive if archive_outputs else bids
        analysis_confound_source = confound_archive if archive_outputs else confound
        cleaned_timeseries = (
            analysis_confound_source
            / "confound_correction_datasink"
            / "cleaned_timeseries"
        )
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(analysis_preprocess_workflow))} "
            f"|| ! -d {shlex.quote(str(analysis_bids_source))} "
            f"|| ! -f {shlex.quote(str(analysis_confound_workflow))} "
            f"|| ! -d {shlex.quote(str(cleaned_timeseries))} "
            f"|| -z \"$(find {shlex.quote(str(cleaned_timeseries))} "
            "-type f -name '*_cleaned.nii.gz' -print -quit)\" ]]; then",
            '  echo "Confound-correction cleaned timeseries or required preprocessing inputs are missing for $subject session $session_name; run preprocessing and confound correction first." >&2',
            "  exit 1",
            "fi",
        ])
    if pipeline in {"whole_pipeline", "analysis_only"}:
        lines.append('mkdir -p "$analysis"')
        if pipeline == "whole_pipeline" and archive_outputs:
            lines.extend([
                f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
                f"&& -f {shlex.quote(str(confound_archive / confound_workflow.name))} "
                f"&& -f {shlex.quote(str(confound_archive / confound_cli.name))} "
                f"&& ! -f {shlex.quote(str(analysis_archive / analysis_workflow.name))} ]]; then",
                f"  cp -a {shlex.quote(str(confound_archive / 'confound_correction_datasink'))} \"$confound/\"",
                f"  cp -f {shlex.quote(str(confound_archive / confound_workflow.name))} \"$confound/\"",
                f"  cp -f {shlex.quote(str(confound_archive / confound_cli.name))} \"$confound/\"",
                "fi",
            ])
        if archive_outputs:
            lines.extend([
                f"if [[ ! -f {shlex.quote(str(analysis_archive / analysis_workflow.name))} "
                f"&& ! -f {shlex.quote(str(legacy_analysis_marker))} ]]; then",
                f"  if [[ ! -f {shlex.quote(str(analysis_workflow))} ]]; then",
                f"    {_shell_command(analysis_command)}",
                "  fi",
                f"  mkdir -p {shlex.quote(str(analysis_archive))}",
                f"  echo \"Archiving analysis output to {analysis_archive}\"",
                f"  cp -av \"$analysis/\". {shlex.quote(str(analysis_archive))}/",
                "fi",
            ])
        else:
            lines.extend([
                f"if [[ ! -f {shlex.quote(str(analysis_workflow))} ]]; then",
                f"  {_shell_command(analysis_command)}",
                "fi",
            ])
    if archive_outputs and pipeline not in {"fixrabies_prepare_only", "analysis_only"}:
        lines.extend([
            'mkdir -p "$session_archive"',
            'echo "Archiving session BIDS input to $session_archive"',
            'cp -av "$bids/." "$session_archive/"',
        ])
    if archive_outputs:
        lines.extend([
            'for rabies_output in "$bids" "$preprocess_output" "$confound" "$analysis"; do',
            '  if [[ -L "$rabies_output" ]]; then',
            '    echo "Refusing to delete symlinked RABIES output: $rabies_output" >&2',
            "    exit 1",
            "  fi",
            '  if [[ -d "$rabies_output" ]]; then',
            '    echo "Removing working output after archive: $rabies_output"',
            '    rm -rf -- "$rabies_output"',
            "  fi",
            "done",
        ])
    lines.extend(['echo "Finished subject $subject"', ""])
    return "\n".join(lines)


def cohort_stage_status(
    results_dir: Path, output_dir: Path | None = None
) -> dict[str, bool]:
    """Report completion markers for cohort-wide RABIES and FIXRABIES stages."""
    archive_dir = results_dir / "cohort"
    work_dir = (output_dir or results_dir.parent / "rabies_outputs") / "cohort"

    def stage_exists(name: str, stage: str) -> bool:
        marker = f"rabies_{stage}_workflow.pkl"
        return any(
            (directory / name / marker).is_file()
            for directory in (work_dir, archive_dir)
        )

    confound_dirs = (
        work_dir / "confound" / "confound_correction_datasink" / "cleaned_timeseries",
        archive_dir / "confound" / "confound_correction_datasink" / "cleaned_timeseries",
    )
    analysis_dirs = (work_dir / "analysis", archive_dir / "analysis")
    fix_data_dirs = (
        work_dir / "fixrabies" / "data",
        archive_dir / "fixrabies" / "data",
    )
    return {
        "preprocess": stage_exists("preprocess", "preprocess"),
        "confound": any(
            directory.is_dir()
            and any(directory.rglob("*_cleaned.nii.gz"))
            for directory in confound_dirs
        ),
        "analysis": any(
            all(
                (directory / name).is_dir()
                for name in COHORT_ANALYSIS_ARCHIVE_DIRS
            )
            for directory in analysis_dirs
        ),
        "fixrabies": any(
            path.is_dir() and any(path.iterdir()) for path in fix_data_dirs
        ),
    }


def clear_cohort_output(output_dir: Path) -> int:
    """Remove only cohort working output, preserving scripts and archived results."""
    output_dir = output_dir.expanduser().resolve()
    project_root = Path(__file__).resolve().parent
    protected_paths = (Path.home().resolve(), project_root)
    if (
        any(
            output_dir == path or output_dir in path.parents
            for path in protected_paths
        )
        or project_root in output_dir.parents
    ):
        raise ValueError(f"Refusing to remove contents of protected directory: {output_dir}")
    target = output_dir / "cohort"
    if target.is_symlink() or target.is_file():
        target.unlink()
        return 1
    if target.is_dir():
        shutil.rmtree(target)
        return 1
    return 0


def _copy_archive_directory(
    source: Path,
    destination: Path,
    progress: Callable[[str], None] | None = None,
) -> bool:
    if source.is_symlink():
        raise ValueError(f"Refusing to archive symlinked working output: {source}")
    if not source.is_dir():
        return False
    if destination.is_symlink() or (
        destination.exists() and not destination.is_dir()
    ):
        raise ValueError(f"Archive destination is not a directory: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    copied_files = 0
    if progress is not None:
        progress(f"Copying {source} to {destination}")

    def copy_file(source_file: str, destination_file: str) -> str:
        nonlocal copied_files
        copied = shutil.copy2(source_file, destination_file)
        copied_files += 1
        if progress is not None and copied_files % 100 == 0:
            progress(
                f"Copied {copied_files} files from {source} to {destination}"
            )
        return copied

    logger.info("Copying archive folder: %s -> %s", source, destination)
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        symlinks=True,
        copy_function=copy_file,
    )
    logger.info(
        "Finished archive folder: %s -> %s (%s files)",
        source,
        destination,
        copied_files,
    )
    if progress is not None:
        progress(
            f"Finished copying {source.name} ({copied_files} files)"
        )
    return True


def _validate_archive_roots(output_dir: Path, results_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.expanduser()
    results_dir = results_dir.expanduser()
    if output_dir.is_symlink() or results_dir.is_symlink():
        raise ValueError("The output and results directories cannot be symlinks.")
    output_dir = output_dir.resolve()
    results_dir = results_dir.resolve()
    if (
        output_dir == results_dir
        or output_dir in results_dir.parents
        or results_dir in output_dir.parents
    ):
        raise ValueError("The output and results directories must be separate.")
    return output_dir, results_dir


def archive_subject_outputs(
    subjects: list[str],
    output_dir: Path,
    results_dir: Path,
    sessions_by_subject: dict[str, list[str]] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Copy existing per-session RABIES outputs into their results layout."""
    output_dir, results_dir = _validate_archive_roots(output_dir, results_dir)

    for subject in subjects:
        if not subject or Path(subject).name != subject or subject in {".", ".."}:
            raise ValueError(f"Invalid subject directory name: {subject!r}")

    working_root = output_dir / SINGLE_SUBJECT_OUTPUT_DIR
    if working_root.is_symlink():
        raise ValueError(
            f"Refusing to archive symlinked working output: {working_root}"
        )
    stages = (
        "tmp_bids_session",
        "func_preprocess",
        "func_confound",
        "func_analysis",
    )
    archive_root = results_dir / SINGLE_SUBJECT_OUTPUT_DIR
    archived: list[Path] = []
    for subject in subjects:
        if progress is not None:
            progress(f"Checking working output for {subject}")
        subject_stage_dirs = [
            working_root / stage / subject for stage in stages
        ]
        for stage_dir in subject_stage_dirs:
            if stage_dir.is_symlink():
                raise ValueError(
                    f"Refusing to archive symlinked working output: {stage_dir}"
                )
        session_names = {
            entry.name
            for stage_dir in subject_stage_dirs
            if stage_dir.is_dir() and not stage_dir.is_symlink()
            for entry in stage_dir.iterdir()
            if entry.is_dir()
        }
        for stage_dir in subject_stage_dirs:
            if stage_dir.is_dir():
                for entry in stage_dir.iterdir():
                    if entry.is_symlink():
                        raise ValueError(
                            "Refusing to archive symlinked working output: "
                            f"{entry}"
                        )
        if sessions_by_subject is not None:
            selected_sessions = sessions_by_subject.get(subject, [])
            for session in selected_sessions:
                _session_result_name(session)
            session_names.intersection_update(
                _session_result_name(session) for session in selected_sessions
            )

        for session_name in sorted(session_names):
            for stage, stage_dir in zip(stages, subject_stage_dirs):
                source = stage_dir / session_name
                destination = archive_root / stage / subject / session_name
                if (
                    archive_root.is_symlink()
                    or (archive_root / stage).is_symlink()
                    or (archive_root / stage / subject).is_symlink()
                    or (archive_root / stage / subject / session_name).is_symlink()
                ):
                    raise ValueError(
                        f"Refusing to archive through a symlink: {destination}"
                    )
                if _copy_archive_directory(source, destination, progress):
                    archived.append(destination)
    logger.info("Archived %s subject output folder(s)", len(archived))
    return archived


def archive_cohort_outputs(
    output_dir: Path,
    results_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> list[Path]:
    """Copy existing cohort RABIES/FIXRABIES outputs into cohort results."""
    output_dir, results_dir = _validate_archive_roots(output_dir, results_dir)
    cohort_output = output_dir / "cohort"
    cohort_results = results_dir / "cohort"
    stages = ("preprocess", "confound", "analysis", "fixrabies")
    archived = []
    for stage in stages:
        source = cohort_output / stage
        destination = cohort_results / stage
        if source.is_symlink() or (cohort_output.is_symlink()):
            raise ValueError(
                f"Refusing to archive symlinked working output: {source}"
            )
        if cohort_results.is_symlink() or destination.is_symlink():
            raise ValueError(f"Refusing to archive through a symlink: {destination}")
        if stage == "preprocess":
            source = source / "preprocess_QC_report"
            destination = destination / "preprocess_QC_report"
            if destination.parent.is_symlink():
                raise ValueError(
                    f"Refusing to archive through a symlink: {destination}"
                )
        elif stage == "confound":
            source = (
                source / "confound_correction_datasink" / "cleaned_timeseries"
            )
            destination = (
                destination / "confound_correction_datasink" / "cleaned_timeseries"
            )
            if (
                (cohort_output / stage / "confound_correction_datasink").is_symlink()
                or destination.parent.is_symlink()
            ):
                raise ValueError(
                    f"Refusing to archive through a symlink: {destination}"
                )
        elif stage == "analysis":
            copied_analysis = False
            for directory_name in COHORT_ANALYSIS_ARCHIVE_DIRS:
                analysis_source = source / directory_name
                analysis_destination = destination / directory_name
                if analysis_destination.is_symlink():
                    raise ValueError(
                        f"Refusing to archive through a symlink: "
                        f"{analysis_destination}"
                    )
                copied_analysis = (
                    _copy_archive_directory(
                        analysis_source, analysis_destination, progress
                    )
                    or copied_analysis
                )
            if destination.is_dir():
                for previous_archive in destination.iterdir():
                    if previous_archive.name in COHORT_ANALYSIS_ARCHIVE_DIRS:
                        continue
                    if previous_archive.is_symlink() or previous_archive.is_file():
                        previous_archive.unlink()
                    elif previous_archive.is_dir():
                        shutil.rmtree(previous_archive)
                    logger.info(
                        "Removed non-datasink cohort analysis archive: %s",
                        previous_archive,
                    )
            if progress is not None:
                progress(
                    "Kept only commonspace_analysis_datasink and "
                    "data_diagnosis_datasink in the cohort analysis archive"
                )
            if copied_analysis:
                archived.append(destination)
            continue
        copied = _copy_archive_directory(source, destination, progress)
        if stage in {"preprocess", "confound"}:
            allowed_root = (
                "preprocess_QC_report"
                if stage == "preprocess"
                else "confound_correction_datasink"
            )
            archive_stage = (
                destination.parent.parent
                if stage == "confound"
                else destination.parent
            )
            if archive_stage.is_dir():
                for previous_archive in archive_stage.iterdir():
                    if previous_archive.name == allowed_root:
                        continue
                    if previous_archive.is_symlink() or previous_archive.is_file():
                        previous_archive.unlink()
                    elif previous_archive.is_dir():
                        shutil.rmtree(previous_archive)
                    logger.info(
                        "Removed nonessential cohort %s archive: %s",
                        stage,
                        previous_archive,
                    )
                if stage == "confound" and destination.parent.is_dir():
                    for previous_archive in destination.parent.iterdir():
                        if previous_archive.name == "cleaned_timeseries":
                            continue
                        if previous_archive.is_symlink() or previous_archive.is_file():
                            previous_archive.unlink()
                        elif previous_archive.is_dir():
                            shutil.rmtree(previous_archive)
                        logger.info(
                            "Removed non-timeseries confound archive: %s",
                            previous_archive,
                        )
                if progress is not None:
                    progress(
                        (
                            "Kept only preprocess_QC_report in the cohort "
                            "preprocessing archive"
                            if stage == "preprocess"
                            else "Kept only cleaned_timeseries in the cohort "
                            "confound archive"
                        )
                    )
        if copied:
            archived.append(destination)
    logger.info("Archived %s cohort output folder(s)", len(archived))
    return archived


class ArchiveWorker(QObject):
    progress = Signal(str)
    succeeded = Signal(list)
    failed = Signal(str)

    def __init__(
        self,
        cohort_mode: bool,
        output_dir: Path,
        results_dir: Path,
        subjects: list[str],
        sessions_by_subject: dict[str, list[str]] | None,
    ) -> None:
        super().__init__()
        self.cohort_mode = cohort_mode
        self.output_dir = output_dir
        self.results_dir = results_dir
        self.subjects = subjects
        self.sessions_by_subject = sessions_by_subject

    def run(self) -> None:
        try:
            if self.cohort_mode:
                archived = archive_cohort_outputs(
                    self.output_dir, self.results_dir, self.progress.emit
                )
            else:
                archived = archive_subject_outputs(
                    self.subjects,
                    self.output_dir,
                    self.results_dir,
                    self.sessions_by_subject,
                    self.progress.emit,
                )
        except Exception as error:
            logger.exception("Manual archive failed")
            self.failed.emit(f"{type(error).__name__}: {error}")
        else:
            self.succeeded.emit(archived)


def generate_cohort_script(
    bids_dir: Path,
    results_dir: Path,
    templates_dir: Path,
    rabies_image: Path,
    preprocess_args: str = PREPROCESS_ARGS,
    confound_args: str = CONFOUND_ARGS,
    analysis_args: str = ANALYSIS_ARGS,
    pipeline: str = "whole_pipeline",
    fix_species: str = "ratSIGMA",
    subject_prefix: str = "sub-",
    output_dir: Path | None = None,
    archive_outputs: bool = True,
    template_files: Mapping[str, str | Path] | None = None,
) -> str:
    """Build one resumable RABIES or FIXRABIES job for a BIDS dataset."""
    bids_dir = bids_dir.expanduser().resolve()
    results_dir = results_dir.expanduser().resolve()
    cohort_archive = results_dir / "cohort"
    output_root = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else results_dir.parent / "rabies_outputs"
    )
    cohort_output = output_root / "cohort"
    for path in (output_root, results_dir):
        if (
            bids_dir == path
            or bids_dir in path.parents
            or path in bids_dir.parents
        ):
            raise ValueError(
                "The output and results directories must be outside and separate "
                "from the input BIDS directory."
            )
    if (
        output_root == results_dir
        or output_root in results_dir.parents
        or results_dir in output_root.parents
    ):
        raise ValueError("The output and results directories must be separate.")
    subjects = discover_subjects(bids_dir, subject_prefix)
    if not subjects:
        raise ValueError(f"No BIDS subjects found in {bids_dir}.")
    if pipeline not in {variant for _, variant in COHORT_PIPELINE_VARIANTS}:
        raise ValueError(f"Unknown cohort pipeline variant: {pipeline}")
    if fix_species not in FIXRABIES_SPECIES:
        raise ValueError(f"Unsupported FIXRABIES species: {fix_species}")

    preprocess = cohort_output / "preprocess"
    confound = cohort_output / "confound"
    analysis = cohort_output / "analysis"
    fix_dir = cohort_output / "fixrabies"
    preprocess_archive = cohort_archive / "preprocess"
    confound_archive = cohort_archive / "confound"
    analysis_archive = cohort_archive / "analysis"
    fix_archive = cohort_archive / "fixrabies"
    templates, template_binds = _resolve_template_files(template_files)

    def bind(host_path: Path, container_path: str, read_only: bool = False) -> str:
        suffix = ":ro" if read_only else ""
        return f"{host_path}:{container_path}{suffix}"

    command_base = ["apptainer", "run"]
    preprocess_command = command_base + [
        "-B", bind(bids_dir, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "-p", "MultiProc", "--local_threads", "8",
        "preprocess", "/input_bids/", "/preprocess_outputs/",
    ] + shlex.split(_expand_template_paths(preprocess_args, templates))
    confound_command = command_base + [
        "-B", bind(bids_dir, "/input_bids", True),
        "-B", bind(preprocess, "/preprocess_outputs"),
        "-B", bind(confound, "/confound_correction_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "-p", "MultiProc", "--local_threads", "8",
        "confound_correction",
        "/preprocess_outputs/", "/confound_correction_outputs/",
    ] + shlex.split(confound_args)
    analysis_confound_source = (
        confound_archive
        if pipeline == "analysis_only" and archive_outputs
        else confound
    )
    analysis_preprocess_source = (
        preprocess
    )
    analysis_command = command_base + [
        "-B", bind(bids_dir, "/input_bids", True),
        "-B", bind(analysis_preprocess_source, "/preprocess_outputs", True),
        "-B", bind(
            analysis_confound_source,
            "/confound_correction_outputs",
            pipeline == "analysis_only" and archive_outputs,
        ),
        "-B", bind(analysis, "/analysis_outputs"),
        "-B", bind(templates_dir, "/templates", True),
    ] + template_binds + [
        str(rabies_image), "-f", "-p", "MultiProc", "--local_threads", "8",
        "analysis", "/confound_correction_outputs/", "/analysis_outputs/",
    ] + shlex.split(_expand_template_paths(analysis_args, templates))
    fix_prepare_command = [
        "fixrabies", "prepare",
        "-preprocess_dir", str(preprocess),
        "-fix_dir", str(fix_dir),
        "-species", fix_species,
        "-nipype", '{"plugin":"MultiProc","n_procs":8}',
    ]

    preprocess_workflow = _workflow_path(preprocess, "preprocess")
    archived_preprocess_workflow = _workflow_path(preprocess_archive, "preprocess")
    confound_workflow = _workflow_path(confound, "confound_correction")
    archived_confound_workflow = _workflow_path(
        confound_archive, "confound_correction"
    )
    analysis_workflow = _workflow_path(analysis, "analysis")
    archived_analysis_workflow = _workflow_path(analysis_archive, "analysis")
    lines = [
        "#!/usr/bin/env bash",
        "#SBATCH --time=48:00:00",
        "#SBATCH --nodes=1",
        "#SBATCH --ntasks=1",
        "#SBATCH --mem=64G",
        "#SBATCH --cpus-per-task=32",
        "set -euo pipefail",
        f"cohort={shlex.quote(str(cohort_output))}",
        f"cohort_archive={shlex.quote(str(cohort_archive))}",
        f"preprocess={shlex.quote(str(preprocess))}",
        f"preprocess_archive={shlex.quote(str(preprocess_archive))}",
        f"confound={shlex.quote(str(confound))}",
        f"confound_archive={shlex.quote(str(confound_archive))}",
        f"analysis={shlex.quote(str(analysis))}",
        f"analysis_archive={shlex.quote(str(analysis_archive))}",
        f"fix_dir={shlex.quote(str(fix_dir))}",
        f"fix_archive={shlex.quote(str(fix_archive))}",
        f"bids_source={shlex.quote(str(bids_dir))}",
        (
            'for output_path in "$cohort" "$cohort_archive"; do'
            if archive_outputs
            else 'for output_path in "$cohort"; do'
        ),
        '  if [[ -L "$output_path" ]]; then',
        '    echo "Refusing to use symlinked cohort output path: $output_path" >&2',
        "    exit 1",
        "  fi",
        "done",
        'if [[ ! -d "$bids_source" ]]; then',
        '  echo "BIDS input directory not found: $bids_source" >&2',
        "  exit 1",
        "fi",
        (
            'mkdir -p "$cohort" "$cohort_archive"'
            if archive_outputs
            else 'mkdir -p "$cohort"'
        ),
        f"echo {shlex.quote(f'Running RABIES on {len(subjects)} subjects from {bids_dir}')}",
    ]
    if pipeline not in {"analysis_only", "fixrabies_prepare_only"}:
        lines.append('mkdir -p "$preprocess"')
    if pipeline in {"preproc_confound", "whole_pipeline"}:
        lines.append('mkdir -p "$confound"')
    if pipeline in {"whole_pipeline", "analysis_only"}:
        lines.append('mkdir -p "$analysis"')
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
        lines.append('mkdir -p "$fix_dir"')
    if pipeline not in {"analysis_only", "fixrabies_prepare_only"}:
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} "
            f"&& -f {shlex.quote(str(archived_preprocess_workflow))} ]]; then",
            '  mkdir -p "$preprocess"',
            '  cp -a "$preprocess_archive/." "$preprocess/"',
            "fi",
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} ]]; then",
            "  " + _shell_command(preprocess_command),
            "fi",
            *(
                [
                    'if [[ -d "$preprocess/preprocess_QC_report" ]]; then',
                    '  if [[ -L "$preprocess/preprocess_QC_report" || -L "$preprocess_archive" || -L "$preprocess_archive/preprocess_QC_report" ]]; then',
                    '    echo "Refusing to archive symlinked cohort preprocessing QC output." >&2',
                    "    exit 1",
                    "  fi",
                    '  echo "Archiving cohort preprocessing QC report to $preprocess_archive/preprocess_QC_report"',
                    '  mkdir -p "$preprocess_archive"',
                    '  cp -av "$preprocess/preprocess_QC_report" "$preprocess_archive/"',
                    '  find "$preprocess_archive" -mindepth 1 -maxdepth 1 ! -name "preprocess_QC_report" -exec rm -rf -- {} +',
                    "fi",
                ]
                if archive_outputs
                else []
            ),
        ])
    if pipeline == "fixrabies_prepare_only":
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} "
            f"&& -f {shlex.quote(str(archived_preprocess_workflow))} ]]; then",
            '  mkdir -p "$preprocess"',
            '  cp -a "$preprocess_archive/." "$preprocess/"',
            "fi",
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} ]]; then",
            '  echo "Working preprocessing output is missing; run preprocessing first." >&2',
            "  exit 1",
            "fi",
        ])
    if pipeline in {"preproc_confound", "whole_pipeline"}:
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
            f"&& -f {shlex.quote(str(archived_confound_workflow))} ]]; then",
            '  mkdir -p "$confound"',
            '  cp -a "$confound_archive/." "$confound/"',
            "fi",
            f"if [[ ! -f {shlex.quote(str(confound_workflow))} ]]; then",
            "  " + _shell_command(confound_command),
            "fi",
            *(
                [
                    'if [[ ! -d "$confound/confound_correction_datasink/cleaned_timeseries" ]]; then',
                    '  echo "Confound-correction cleaned_timeseries folder is missing; cannot archive cohort confound output." >&2',
                    "  exit 1",
                    "fi",
                    'if [[ -L "$confound/confound_correction_datasink" || -L "$confound/confound_correction_datasink/cleaned_timeseries" || -L "$confound_archive" || -L "$confound_archive/confound_correction_datasink" || -L "$confound_archive/confound_correction_datasink/cleaned_timeseries" ]]; then',
                    '  echo "Refusing to archive symlinked cohort confound output." >&2',
                    "  exit 1",
                    "fi",
                    'echo "Archiving cohort cleaned timeseries to $confound_archive/confound_correction_datasink/cleaned_timeseries"',
                    'mkdir -p "$confound_archive/confound_correction_datasink"',
                    'cp -av "$confound/confound_correction_datasink/cleaned_timeseries" "$confound_archive/confound_correction_datasink/"',
                    'find "$confound_archive" -mindepth 1 -maxdepth 1 ! -name "confound_correction_datasink" -exec rm -rf -- {} +',
                    'find "$confound_archive/confound_correction_datasink" -mindepth 1 -maxdepth 1 ! -name "cleaned_timeseries" -exec rm -rf -- {} +',
                ]
                if archive_outputs
                else []
            ),
        ])
    if pipeline == "analysis_only":
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(preprocess_workflow))} "
            f"&& -f {shlex.quote(str(archived_preprocess_workflow))} ]]; then",
            '  mkdir -p "$preprocess"',
            '  cp -a "$preprocess_archive/." "$preprocess/"',
            "fi",
        ])
        if not archive_outputs:
            lines.extend([
                f"if [[ ! -f {shlex.quote(str(confound_workflow))} "
                f"&& -f {shlex.quote(str(archived_confound_workflow))} ]]; then",
                '  mkdir -p "$confound"',
                '  cp -a "$confound_archive/." "$confound/"',
                "fi",
            ])
        analysis_preprocess_workflow = preprocess_workflow
        analysis_confound_source = confound_archive if archive_outputs else confound
        cleaned_timeseries = (
            analysis_confound_source
            / "confound_correction_datasink"
            / "cleaned_timeseries"
        )
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(analysis_preprocess_workflow))} "
            f"|| ! -d {shlex.quote(str(cleaned_timeseries))} "
            f"|| -z \"$(find {shlex.quote(str(cleaned_timeseries))} "
            "-type f -name '*_cleaned.nii.gz' -print -quit)\" ]]; then",
            '  echo "Cohort confound-correction cleaned timeseries are missing; run confound correction first." >&2',
            "  exit 1",
            "fi",
        ])
    analysis_archive_lines = [
        'if [[ -L "$analysis_archive" '
        + " || "
        + " || ".join(
            f'-L "$analysis/{name}" || -L "$analysis_archive/{name}"'
            for name in COHORT_ANALYSIS_ARCHIVE_DIRS
        )
        + " ]]; then",
        '  echo "Refusing to archive symlinked cohort analysis output." >&2',
        "  exit 1",
        "fi",
        'mkdir -p "$analysis_archive"',
        "echo \"Archiving selected cohort analysis datasinks to $analysis_archive\"",
    ]
    for directory_name in COHORT_ANALYSIS_ARCHIVE_DIRS:
        analysis_archive_lines.extend([
            f'if [[ -d "$analysis/{directory_name}" ]]; then',
            f'  cp -av "$analysis/{directory_name}" "$analysis_archive/"',
            "fi",
        ])
    analysis_archive_lines.append(
        'find "$analysis_archive" -mindepth 1 -maxdepth 1 '
        + " ".join(
            f'! -name "{name}"' for name in COHORT_ANALYSIS_ARCHIVE_DIRS
        )
        + " -exec rm -rf -- {} +"
    )
    if pipeline in {"whole_pipeline", "analysis_only"}:
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(analysis_workflow))} "
            f"&& -f {shlex.quote(str(archived_analysis_workflow))} ]]; then",
            '  mkdir -p "$analysis"',
            '  cp -a "$analysis_archive/." "$analysis/"',
            "fi",
            f"if [[ ! -f {shlex.quote(str(analysis_workflow))} ]]; then",
            "  " + _shell_command(analysis_command),
            "fi",
            *(
                analysis_archive_lines
                if archive_outputs
                else []
            ),
        ])
    if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
        fix_data = fix_dir / "data"
        fix_marker = fix_dir / ".prepare_complete"
        archived_fix_marker = fix_archive / ".prepare_complete"
        lines.extend([
            f"if [[ ! -f {shlex.quote(str(fix_marker))} "
            f"&& -f {shlex.quote(str(archived_fix_marker))} ]]; then",
            '  mkdir -p "$fix_dir"',
            '  cp -a "$fix_archive/." "$fix_dir/"',
            "fi",
            f"if [[ -d {shlex.quote(str(fix_data))} "
            f"&& -n \"$(find {shlex.quote(str(fix_data))} -mindepth 1 "
            f"-maxdepth 1 -print -quit)\" "
            f"&& ! -f {shlex.quote(str(fix_marker))} ]]; then",
            '  echo "Existing FIXRABIES data found; clear cohort results before preparing again." >&2',
            "  exit 1",
            "fi",
            f"if [[ ! -f {shlex.quote(str(fix_marker))} ]]; then",
            '  if ! command -v fixrabies >/dev/null 2>&1; then',
            '    echo "FIXRABIES CLI (fixrabies) is not available on PATH in this job environment." >&2',
            "    exit 127",
            "  fi",
            "  " + _shell_command(fix_prepare_command),
            f"  touch {shlex.quote(str(fix_marker))}",
            "fi",
            *(
                [
                    'mkdir -p "$fix_archive"',
                    'echo "Archiving cohort FIXRABIES output to $fix_archive"',
                    'cp -av "$fix_dir/." "$fix_archive/"',
                ]
                if archive_outputs
                else []
            ),
        ])
    lines.append(f'echo "Finished cohort {pipeline.replace("_", " ")}"')
    if archive_outputs:
        lines.extend([
            'if [[ -L "$cohort" ]]; then',
            '  echo "Refusing to delete symlinked cohort working output: $cohort" >&2',
            "  exit 1",
            "fi",
            'for working_stage in "$cohort/confound" "$cohort/analysis" "$cohort/fixrabies"; do',
            '  if [[ -L "$working_stage" ]]; then',
            '    echo "Refusing to delete symlinked cohort working output: $working_stage" >&2',
            "    exit 1",
            "  fi",
            '  if [[ -d "$working_stage" ]]; then',
            '    echo "Removing archived cohort working output: $working_stage"',
            '    rm -rf -- "$working_stage"',
            "  fi",
            "done",
            'echo "Keeping cohort preprocessing output in place; only its QC report was archived."',
        ])
    lines.append("")
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
            "Choose the project folders and template set, then continue to the analysis manager."
        ))

        paths = QWidget()
        path_layout = QFormLayout(paths)
        defaults = (
            ("Project root", "root", str(Path.cwd())),
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
        open_manager = QPushButton("Open analysis manager")
        open_manager.clicked.connect(self.open_subject_manager)
        controls.addWidget(open_manager)
        layout.addLayout(controls)
        self.status = QLabel("Select a project root and original BIDS folder.")
        layout.addWidget(self.status)
        self.path_fields["root"].textChanged.connect(self._populate_bids_folders)
        self.path_fields["root"].editingFinished.connect(self._update_project_output_defaults)
        self._update_project_output_defaults()
        self._populate_bids_folders()

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
        preferred_folder = Path(root_value).expanduser() / "bids"
        for folder in folders:
            self.bids_folders.addItem(folder.name, str(folder))
        selected_index = (
            self.bids_folders.findData(previously_selected)
            if previously_selected
            else -1
        )
        if selected_index < 0:
            selected_index = self.bids_folders.findData(str(preferred_folder))
        if selected_index >= 0:
            self.bids_folders.setCurrentIndex(selected_index)
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
        self.path_fields["output"].setText(str(root / "rabies_outputs"))
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
        self.setWindowTitle("RABIES Analysis Manager")
        self.resize(1180, 900)
        self.setMinimumSize(900, 740)
        self.stage_args = {
            "Preprocessing": PREPROCESS_ARGS,
            "Confound correction": CONFOUND_ARGS,
            "Analysis": ANALYSIS_ARGS,
        }
        self.template_files: dict[str, str] = {}
        self._archive_thread: QThread | None = None
        self._archive_worker: ArchiveWorker | None = None
        self._build_ui()
        self.update_project_label()
        self.refresh_subjects()

    def _pipeline_cards(
        self,
        selector: QComboBox,
        variants: tuple[tuple[str, str], ...],
    ) -> QWidget:
        cards = QWidget()
        grid = QGridLayout(cards)
        grid.setContentsMargins(0, 0, 0, 0)
        group = QButtonGroup(cards)
        group.setExclusive(True)
        buttons: dict[str, QPushButton] = {}
        for index, (label, variant) in enumerate(variants):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setMinimumHeight(48)
            button.setStyleSheet(
                "QPushButton { border: 2px solid #5f6368; padding: 8px; "
                "font-weight: 600; } "
                "QPushButton:checked { border: 3px solid #8ab4f8; "
                "background-color: #2b4d7e; }"
            )
            group.addButton(button)
            buttons[variant] = button
            grid.addWidget(button, index // 2, index % 2)
            button.clicked.connect(
                lambda _checked=False, selected=variant: selector.setCurrentIndex(
                    selector.findData(selected)
                )
            )

        def update_checked(_index: int = -1) -> None:
            selected = selector.currentData()
            for variant, button in buttons.items():
                button.setChecked(variant == selected)

        selector.currentIndexChanged.connect(update_checked)
        update_checked()
        return cards

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

        mode_options = QHBoxLayout()
        mode_options.addWidget(QLabel("Analysis mode:"))
        self.mode_selector = QComboBox()
        self.mode_selector.addItem(
            "Single-subject/session scripts and batch jobs", "single_subject"
        )
        self.mode_selector.addItem("Cohort script and batch job", "cohort")
        self.mode_selector.setCurrentIndex(1)
        mode_options.addWidget(self.mode_selector)
        mode_options.addStretch()
        layout.addLayout(mode_options)
        self.cohort_stage_label = QLabel()
        layout.addWidget(self.cohort_stage_label)

        self.subjects = QTableWidget(0, 8)
        self.subjects.setHorizontalHeaderLabels(
            [
                "Subject", "BOLD scans", "T2w scans", "Preprocess", "Confound",
                "Analysis", "FIXRABIES", "FIX folder(s)",
            ]
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
        self.session_details = QTableWidget(0, 7)
        self.session_details.setHorizontalHeaderLabels([
            "Session",
            "NIfTI orientations",
            "Session archive",
            "Session preprocess",
            "Session confound",
            "Session analysis",
            "Session FIXRABIES",
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

        common_options = QHBoxLayout()
        for label, callback in (
            ("Refresh subjects", self.refresh_subjects),
            ("Select all", self.select_all),
            ("Clear selection", self.clear_selection),
            ("Move cleaned timeseries", self.move_selected_cleaned_timeseries),
            ("Reorient selected NIfTIs to RAS", self.reorient_selected_niftis),
            ("RABIES arguments…", self.edit_arguments),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            common_options.addWidget(button)
        self.archive_button = QPushButton("Archive existing output")
        self.archive_button.clicked.connect(self.archive_existing_output)
        common_options.addWidget(self.archive_button)
        common_options.addStretch()
        layout.addLayout(common_options)

        self.archive_outputs = QCheckBox("Archiving")
        self.archive_outputs.setChecked(True)
        self.archive_outputs.setToolTip(
            "When checked, archive stage results to rabies_results and remove "
            "the RABIES working outputs after a successful archive. When "
            "unchecked, do not archive results and retain working outputs."
        )
        output_retention_options = QHBoxLayout()
        output_retention_options.addWidget(self.archive_outputs)
        output_retention_options.addStretch()
        layout.addLayout(output_retention_options)

        self.single_subject_controls = QWidget()
        single_subject_layout = QVBoxLayout(self.single_subject_controls)
        single_subject_layout.setContentsMargins(0, 0, 0, 0)
        options = QHBoxLayout()
        for label, callback in (
            ("Remove selected scripts", self.remove_scripts),
            ("Submit scripts with sbatch", self.submit_scripts),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            options.addWidget(button)
        self.pipeline_selector = QComboBox()
        for label, pipeline in PIPELINE_VARIANTS:
            self.pipeline_selector.addItem(label, pipeline)
        self.pipeline_selector.setCurrentIndex(
            self.pipeline_selector.findData("whole_pipeline")
        )
        self.pipeline_selector.hide()
        create_scripts = QPushButton("Create script")
        create_scripts.clicked.connect(self.create_scripts)
        options.addWidget(create_scripts)
        single_subject_layout.addLayout(options)

        pipeline_options = QHBoxLayout()
        pipeline_options.addWidget(QLabel("Workflow mode:"))
        self.pipeline_mode_selector = QComboBox()
        self.pipeline_mode_selector.addItem("Normal mode", "normal")
        self.pipeline_mode_selector.addItem("FIX mode", "fix")
        pipeline_options.addWidget(self.pipeline_mode_selector)
        self.normal_pipeline_cards = self._pipeline_cards(
            self.pipeline_selector, NORMAL_PIPELINE_VARIANTS
        )
        self.fix_pipeline_cards = self._pipeline_cards(
            self.pipeline_selector, FIX_PIPELINE_VARIANTS
        )
        pipeline_options.addWidget(self.normal_pipeline_cards, 1)
        pipeline_options.addWidget(self.fix_pipeline_cards, 1)
        single_subject_layout.addLayout(pipeline_options)

        self.fix_species_selector = QComboBox()
        self.fix_species_selector.addItems(FIXRABIES_SPECIES)
        self.fix_species_selector.setToolTip(
            "Choose the FIXRABIES species that matches the RABIES common-space template."
        )
        self.fix_directory_selector = QComboBox()
        self.fix_directory_selector.setMinimumWidth(210)
        self.fix_directory_selector.setToolTip(
            "Create a new shared project-level folder or add these subjects to an existing FIXRABIES folder."
        )
        self.fix_directory_name = QLineEdit()
        self.fix_directory_name.setPlaceholderText(
            "Optional custom name; blank uses an automatic name"
        )
        self.fix_directory_name.setToolTip(
            "Name a new FIX folder inside the project root. Enter one folder name, not a path."
        )
        self.pipeline_selector.currentIndexChanged.connect(
            self._update_fix_controls
        )
        self.pipeline_mode_selector.currentIndexChanged.connect(
            self._update_fix_controls
        )
        self.fix_directory_selector.currentIndexChanged.connect(
            self._update_fix_controls
        )
        self.fix_options = QWidget()
        fix_options = QHBoxLayout(self.fix_options)
        fix_options.setContentsMargins(0, 0, 0, 0)
        fix_options.addWidget(QLabel("FIX species:"))
        fix_options.addWidget(self.fix_species_selector)
        fix_options.addWidget(QLabel("FIX folder:"))
        fix_options.addWidget(self.fix_directory_selector)
        fix_options.addWidget(QLabel("New folder name:"))
        fix_options.addWidget(self.fix_directory_name, 1)
        single_subject_layout.addWidget(self.fix_options)

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
        single_subject_layout.addLayout(cleanup_options)
        layout.addWidget(self.single_subject_controls)

        self.cohort_controls = QWidget()
        cohort_controls_layout = QVBoxLayout(self.cohort_controls)
        cohort_controls_layout.setContentsMargins(0, 0, 0, 0)
        self.cohort_pipeline_selector = QComboBox()
        for label, pipeline in COHORT_PIPELINE_VARIANTS:
            self.cohort_pipeline_selector.addItem(label, pipeline)
        self.cohort_pipeline_selector.setCurrentIndex(
            self.cohort_pipeline_selector.findData("whole_pipeline")
        )
        self.cohort_pipeline_selector.hide()

        cohort_pipeline_options = QHBoxLayout()
        cohort_pipeline_options.addWidget(QLabel("Workflow mode:"))
        self.cohort_pipeline_mode_selector = QComboBox()
        self.cohort_pipeline_mode_selector.addItem("Normal mode", "normal")
        self.cohort_pipeline_mode_selector.addItem("FIX mode", "fix")
        cohort_pipeline_options.addWidget(self.cohort_pipeline_mode_selector)
        self.cohort_normal_pipeline_cards = self._pipeline_cards(
            self.cohort_pipeline_selector, NORMAL_PIPELINE_VARIANTS
        )
        self.cohort_fix_pipeline_cards = self._pipeline_cards(
            self.cohort_pipeline_selector, FIX_PIPELINE_VARIANTS
        )
        cohort_pipeline_options.addWidget(self.cohort_normal_pipeline_cards, 1)
        cohort_pipeline_options.addWidget(self.cohort_fix_pipeline_cards, 1)
        cohort_controls_layout.addLayout(cohort_pipeline_options)

        self.cohort_fix_species_selector = QComboBox()
        self.cohort_fix_species_selector.addItems(FIXRABIES_SPECIES)
        self.cohort_fix_species_selector.setToolTip(
            "Choose the FIXRABIES species that matches the RABIES common-space template."
        )
        self.cohort_fix_options = QWidget()
        cohort_fix_options = QHBoxLayout(self.cohort_fix_options)
        cohort_fix_options.setContentsMargins(0, 0, 0, 0)
        cohort_fix_options.addWidget(QLabel("FIX species:"))
        cohort_fix_options.addWidget(self.cohort_fix_species_selector)
        cohort_fix_options.addStretch()
        cohort_controls_layout.addWidget(self.cohort_fix_options)

        cohort_options = QHBoxLayout()
        for label, callback in (
            ("Create cohort script", self.create_cohort_script),
            ("Submit cohort with sbatch", self.submit_cohort_script),
            ("Remove cohort scripts", self.remove_cohort_scripts),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            cohort_options.addWidget(button)
        cohort_controls_layout.addLayout(cohort_options)
        self.cohort_pipeline_selector.currentIndexChanged.connect(
            self._update_cohort_pipeline_controls
        )
        self.cohort_pipeline_mode_selector.currentIndexChanged.connect(
            self._update_cohort_pipeline_controls
        )

        cohort_cleanup = QHBoxLayout()
        cohort_cleanup.addWidget(QLabel("Cohort cleanup:"))
        for label, callback in (
            ("Clear ALL results", self.clear_all_results),
            ("Clear cohort output", self.clear_cohort_outputs),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            cohort_cleanup.addWidget(button)
        cohort_cleanup.addStretch()
        cohort_controls_layout.addLayout(cohort_cleanup)
        layout.addWidget(self.cohort_controls)

        self.status = QLabel(
            "Choose whether to create per-session jobs or one cohort-wide job."
        )
        layout.addWidget(self.status)
        self.mode_selector.currentIndexChanged.connect(self._update_mode_controls)
        self._update_mode_controls()

    def _project_paths(self) -> tuple[Path, Path, Path, Path, Path]:
        return self.setup_window._project_paths()

    def _update_mode_controls(self, _index: int = -1) -> None:
        cohort_mode = self.mode_selector.currentData() == "cohort"
        self._update_fix_controls()
        self._update_cohort_pipeline_controls()
        self.single_subject_controls.setVisible(not cohort_mode)
        self.cohort_controls.setVisible(cohort_mode)
        self.cohort_stage_label.setVisible(cohort_mode)
        if cohort_mode:
            self.session_details.setHorizontalHeaderLabels(
                [
                    "Session",
                    "NIfTI orientations",
                    "Input source",
                    "Cohort preprocess",
                    "Cohort confound",
                    "Cohort analysis",
                    "FIXRABIES prepare",
                ]
            )
            self._refresh_cohort_status()
            message = "Create or submit one pipeline job for the full selected BIDS folder."
        else:
            self.session_details.setHorizontalHeaderLabels(
                [
                    "Session",
                    "NIfTI orientations",
                    "Session archive",
                    "Session preprocess",
                    "Session confound",
                    "Session analysis",
                    "Session FIXRABIES",
                ]
            )
            message = "Create or submit independent jobs for selected subject sessions."
        self.status.setText(message)
        current_row = self.subjects.currentRow()
        if current_row >= 0:
            self._show_session_details(
                current_row, self.subjects.currentColumn(), -1, -1
            )

    def _refresh_cohort_status(self) -> None:
        output_value = self.path_fields["output"].text().strip()
        results_value = self.path_fields["results"].text().strip()
        if not output_value or not results_value:
            self.cohort_stage_label.setText(
                "Cohort-wide stages: output or results directory not set."
            )
            return
        try:
            states = cohort_stage_status(
                Path(results_value).expanduser(),
                Path(output_value).expanduser(),
            )
        except OSError as error:
            QMessageBox.critical(
                self, "Could not read cohort stage status", str(error)
            )
            return
        labels = (
            ("Preprocess", "preprocess"),
            ("Confound", "confound"),
            ("Analysis", "analysis"),
            ("FIXRABIES", "fixrabies"),
        )
        status = " | ".join(
            f"{label}: {'Complete' if states[key] else 'Not found'}"
            for label, key in labels
        )
        self.cohort_stage_label.setText(f"Cohort-wide stages: {status}")

    def _update_fix_controls(self, _index: int = -1) -> None:
        fix_mode = self.pipeline_mode_selector.currentData() == "fix"
        variants = FIX_PIPELINE_VARIANTS if fix_mode else NORMAL_PIPELINE_VARIANTS
        allowed = {variant for _, variant in variants}
        if self.pipeline_selector.currentData() not in allowed:
            default = "fixrabies_prepare" if fix_mode else "whole_pipeline"
            self.pipeline_selector.setCurrentIndex(
                self.pipeline_selector.findData(default)
            )
        self.normal_pipeline_cards.setVisible(not fix_mode)
        self.fix_pipeline_cards.setVisible(fix_mode)
        self.fix_options.setVisible(fix_mode)
        self.fix_species_selector.setEnabled(fix_mode)
        self.fix_directory_selector.setEnabled(fix_mode)
        self.fix_directory_name.setEnabled(
            fix_mode
            and self.fix_directory_selector.currentData() == FIX_CREATE_NEW
        )

    def _update_cohort_pipeline_controls(self, _index: int = -1) -> None:
        fix_mode = self.cohort_pipeline_mode_selector.currentData() == "fix"
        variants = FIX_PIPELINE_VARIANTS if fix_mode else NORMAL_PIPELINE_VARIANTS
        allowed = {variant for _, variant in variants}
        if self.cohort_pipeline_selector.currentData() not in allowed:
            default = "fixrabies_prepare" if fix_mode else "whole_pipeline"
            self.cohort_pipeline_selector.setCurrentIndex(
                self.cohort_pipeline_selector.findData(default)
            )
        self.cohort_normal_pipeline_cards.setVisible(not fix_mode)
        self.cohort_fix_pipeline_cards.setVisible(fix_mode)
        self.cohort_fix_options.setVisible(fix_mode)
        self.cohort_fix_species_selector.setEnabled(fix_mode)

    def _refresh_fix_directory_options(self, project_root: Path) -> None:
        selected = self.fix_directory_selector.currentData()
        self.fix_directory_selector.blockSignals(True)
        try:
            self.fix_directory_selector.clear()
            self.fix_directory_selector.addItem(
                "Create new shared FIX folder…", FIX_CREATE_NEW
            )
            fix_dirs = list_fix_directories(project_root)
            for fix_dir in fix_dirs:
                self.fix_directory_selector.addItem(fix_dir.name, str(fix_dir))
            selected_index = self.fix_directory_selector.findData(selected)
            self.fix_directory_selector.setCurrentIndex(
                selected_index if selected_index >= 0 else 0
            )
        finally:
            self.fix_directory_selector.blockSignals(False)
        self._update_fix_controls()

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
            project_root, output, results, _, _ = self._project_paths()
            self._refresh_fix_directory_options(project_root)
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
                    stage_status(subject, output, results, session, project_root)
                    for session in session_files
                ]
                states = {
                    stage: [session[stage] for session in session_states]
                    for stage in ("preprocess", "confound", "analysis", "fixrabies")
                }
                previous_results = any(
                    subject_has_previous_results(subject, results, session)
                    for session in session_files
                )
                assigned_fix_dirs = fix_directories_for_subject(
                    project_root, subject
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
                    status_text(states["fixrabies"]),
                    ", ".join(fix_dir.name for fix_dir in assigned_fix_dirs) or "—",
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 7 and value != "—":
                        item.setToolTip("\n".join(
                            str(fix_dir) for fix_dir in assigned_fix_dirs
                        ))
                    self.subjects.setItem(row, column, item)
        except OSError as error:
            QMessageBox.critical(
                self, "Could not read FIXRABIES assignments", str(error)
            )
            return
        finally:
            self.subjects.blockSignals(was_blocked)
        self.session_details.setRowCount(0)
        self.session_details_label.setText("Session details: select a subject.")
        self.status.setText(f"Found {len(discovered)} subject(s) in {bids_dir}.")
        if self.mode_selector.currentData() == "cohort":
            self._refresh_cohort_status()

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
        project_root, output, results, _, _ = self._project_paths()
        try:
            sessions = session_nifti_orientations(bids_dir / subject)
        except OSError as error:
            QMessageBox.critical(self, "Could not read session files", str(error))
            return
        if not sessions:
            sessions = {"No session": []}
        cohort_mode = self.mode_selector.currentData() == "cohort"
        cohort_states = (
            cohort_stage_status(results, output) if cohort_mode else None
        )
        session_states = (
            {
                session: stage_status(
                    subject, output, results, session, project_root
                )
                for session in sessions
            }
            if not cohort_mode
            else {}
        )
        rows = [
            (session, path, orientation)
            for session, files in sessions.items()
            for path, orientation in files
        ]
        if not rows:
            rows = [(session, None, "No NIfTI files found") for session in sessions]
        self.session_details.setRowCount(len(rows))
        for row, (session, path, orientation) in enumerate(rows):
            result_session = results / SINGLE_SUBJECT_OUTPUT_DIR
            archived_stage_dirs = (
                "tmp_bids_session",
                "func_preprocess",
                "func_confound",
                "func_analysis",
            )
            archive = (
                "Original BIDS"
                if cohort_mode
                else (
                    "Present"
                    if any(
                        (
                            result_session / stage / subject
                            / _session_result_name(session)
                        ).is_dir()
                        for stage in archived_stage_dirs
                    )
                    else "Not found"
                )
            )
            states = (
                cohort_states
                if cohort_states is not None
                else session_states[session]
            )
            if states is None:
                raise RuntimeError("Cohort stage state is unavailable.")
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
                "Complete" if states["fixrabies"] else "Not found",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1 and path is not None:
                    item.setToolTip(str(path.resolve()))
                self.session_details.setItem(row, column, item)
        self.session_details_label.setText(
            f"Sessions for {subject} "
            f"({'stage results are cohort-wide' if cohort_mode else 'stage results are session-specific'}):"
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
        dialog.resize(850, 600)
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

        template_page = QWidget()
        template_layout = QVBoxLayout(template_page)
        template_layout.addWidget(QLabel(
            "Choose replacement files for template variables. Leave a field blank "
            "to use the default file from the selected template folder."
        ))
        template_form = QFormLayout()
        template_editors: dict[str, QLineEdit] = {}
        for name, relative_path in TEMPLATE_FILE_DEFAULTS.items():
            field = QLineEdit(self.template_files.get(name, ""))
            field.setPlaceholderText(f"Default: /templates/{relative_path}")
            template_editors[name] = field
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(field)
            browse = QPushButton("Browse…")
            browse.clicked.connect(
                lambda _checked=False, key=name, target=field: (
                    self._browse_template_file(dialog, key, target)
                )
            )
            row_layout.addWidget(browse)
            template_form.addRow(TEMPLATE_FILE_LABELS[name], row)
        template_layout.addLayout(template_form)
        template_layout.addStretch()
        tabs.addTab(template_page, "Template files")
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
            self.template_files = {
                name: field.text().strip()
                for name, field in template_editors.items()
                if field.text().strip()
            }
            self.status.setText("RABIES arguments updated for future script generation.")

    def _browse_template_file(
        self, dialog: QDialog, name: str, field: QLineEdit
    ) -> None:
        initial_path = (
            field.text().strip()
            or self.path_fields["templates"].text().strip()
        )
        selected, _ = QFileDialog.getOpenFileName(
            dialog,
            f"Select {TEMPLATE_FILE_LABELS[name]}",
            initial_path,
            "NIfTI files (*.nii *.nii.gz);;All files (*)",
        )
        if selected:
            field.setText(selected)

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
        existing_paths.extend(
            path
            for subject in selected
            for _, variant in PIPELINE_VARIANTS
            for path in (script_dir / variant).glob(f"scrip_{subject}_*.sh")
            if path.is_file()
        )
        if not existing_paths:
            QMessageBox.information(self, "No scripts found", "No generated scripts exist for the selected subjects.")
            return
        answer = QMessageBox.question(
            self,
            "Remove generated scripts",
            f"Remove {len(existing_paths)} selected script(s)? This does not remove processing outputs.",
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
        _, output, results, _, _ = self._project_paths()
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
        if self.mode_selector.currentData() == "cohort" and subjects is not None:
            QMessageBox.information(
                self,
                "Cohort results cannot be cleared per subject",
                "RABIES results are shared across the full BIDS dataset. "
                "Use Clear ALL results to remove the cohort outputs.",
            )
            return
        if subjects is not None:
            targets = [
                results / subject for subject in subjects
            ] + [
                results / SINGLE_SUBJECT_OUTPUT_DIR / stage / subject
                for stage in SUBJECT_ARCHIVE_DIRECTORIES
                for subject in subjects
            ]
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
        if self.mode_selector.currentData() == "cohort":
            self._refresh_cohort_status()
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

    def archive_existing_output(self) -> None:
        if self._archive_thread is not None:
            logger.warning("Manual archive requested while another archive is active")
            return
        output_value = self.path_fields["output"].text().strip()
        results_value = self.path_fields["results"].text().strip()
        if not output_value or not results_value:
            QMessageBox.critical(
                self,
                "Output or results directory not set",
                "Choose a project root or set both output and results directories.",
            )
            return

        output = Path(output_value).expanduser()
        results = Path(results_value).expanduser()
        cohort_mode = self.mode_selector.currentData() == "cohort"
        sessions_by_subject = None
        if cohort_mode:
            scope = f"existing cohort output from {output / 'cohort'}"
        else:
            subjects = self._selected_subjects()
            if not subjects:
                QMessageBox.information(
                    self,
                    "No subjects selected",
                    "Select one or more subjects whose working output you want to archive.",
                )
                return
            if len(subjects) == 1:
                selected_sessions = sorted({
                    item.text()
                    for item in self.session_details.selectedItems()
                    if item.column() == 0
                })
                if selected_sessions:
                    sessions_by_subject = {subjects[0]: selected_sessions}
            scope = (
                f"existing output for {', '.join(subjects)}"
                + (
                    f", sessions {', '.join(sessions_by_subject[subjects[0]])}"
                    if sessions_by_subject
                    else " (all available sessions)"
                )
            )

        answer = QMessageBox.question(
            self,
            "Archive existing RABIES output",
            f"Copy {scope} to {results}?\n"
            "Existing archived files with the same names may be replaced. "
            "Working output will be kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        logger.info(
            "Starting manual %s archive: output=%s results=%s subjects=%s sessions=%s",
            "cohort" if cohort_mode else "single-subject",
            output,
            results,
            subjects if not cohort_mode else "all",
            sessions_by_subject or "all available",
        )
        self.archive_button.setEnabled(False)
        self.status.setText("Starting archive; working output will be kept.")
        thread = QThread(self)
        worker = ArchiveWorker(
            cohort_mode, output, results,
            [] if cohort_mode else subjects,
            sessions_by_subject,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._archive_progress)
        worker.succeeded.connect(self._archive_succeeded)
        worker.failed.connect(self._archive_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._archive_thread_finished)
        self._archive_thread = thread
        self._archive_worker = worker
        thread.start()

    def _archive_progress(self, message: str) -> None:
        logger.info("Archive progress: %s", message)
        self.status.setText(message)

    def _archive_succeeded(self, archived: list[Path]) -> None:
        self.archive_button.setEnabled(True)
        if not archived:
            QMessageBox.information(
                self,
                "No RABIES output found",
                "No existing working output was found to archive.",
            )
            logger.info("Manual archive finished: no working output was found")
            self.status.setText("No existing working output was found.")
            return

        self.refresh_subjects()
        if self.mode_selector.currentData() == "cohort":
            self._refresh_cohort_status()
        logger.info("Manual archive completed: %s folder(s)", len(archived))
        self.status.setText(
            f"Archived {len(archived)} existing output folder(s); "
            "working output was kept."
        )

    def _archive_failed(self, error: str) -> None:
        self.archive_button.setEnabled(True)
        logger.error("Manual archive failed: %s", error)
        self.status.setText("Archiving failed.")
        QMessageBox.critical(
            self, "Could not archive working output", error
        )

    def _archive_thread_finished(self) -> None:
        self._archive_thread = None
        self._archive_worker = None

    def move_selected_cleaned_timeseries(self) -> None:
        selected = self._selected_subjects()
        if not selected:
            QMessageBox.information(
                self, "No subjects selected",
                "Select the subjects whose cleaned timeseries you want to move.",
            )
            return
        _, output, results, _, _ = self._project_paths()
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(self, "Results directory not set", "Choose a project root or set a results directory.")
            return

        destination_dir = results / "cleaned_timeseries"
        answer = QMessageBox.question(
            self,
            "Move cleaned timeseries",
            f"Move cleaned NIfTI files for {len(selected)} selected subject(s) into\n"
            f"{destination_dir}?\nIdentical duplicate copies will be removed. "
            "Different files with the same name will be reported as a conflict.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            moved, removed_duplicates = move_cleaned_timeseries(
                selected,
                results,
                output_dir=output,
                cohort_mode=self.mode_selector.currentData() == "cohort",
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not move cleaned timeseries", str(error))
            return

        self.status.setText(
            f"Moved {len(moved)} cleaned timeseries; removed "
            f"{len(removed_duplicates)} duplicate source copy/copies."
        )
        message = (
            f"Moved {len(moved)} file(s) to {destination_dir}."
            f"\nRemoved {len(removed_duplicates)} identical duplicate source copy/copies."
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

    def create_cohort_script(self) -> None:
        pipeline = self.cohort_pipeline_selector.currentData()
        pipeline_label = self.cohort_pipeline_selector.currentText()
        bids_dir = self._selected_bids_dir()
        if bids_dir is None or not bids_dir.is_dir():
            QMessageBox.critical(
                self,
                "Original BIDS folder not set",
                "Select an existing original BIDS folder before creating the cohort script.",
            )
            return
        _, output, results, templates, image = self._project_paths()
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(
                self, "Output directory not set",
                "Select a project root or set an output directory.",
            )
            return
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(
                self, "Results directory not set",
                "Select a project root or set a results directory.",
            )
            return
        if pipeline != "fixrabies_prepare_only":
            if not templates.is_dir():
                QMessageBox.critical(
                    self, "Templates not found",
                    f"Template directory does not exist: {templates}",
                )
                return
            if not image.is_file():
                QMessageBox.critical(
                    self, "RABIES image not found",
                    f"Apptainer image does not exist: {image}",
                )
                return
        try:
            subjects = discover_subjects(
                bids_dir, self.path_fields["subject_prefix"].text().strip()
            )
            if pipeline == "fixrabies_prepare_only":
                preprocess_locations = (
                    output / "cohort" / "preprocess",
                    results / "cohort" / "preprocess",
                )
                if not any(
                    _workflow_path(location, "preprocess").is_file()
                    for location in preprocess_locations
                ):
                    raise ValueError(
                        "Cohort preprocessing output is missing. Run "
                        "preprocessing first; checked: "
                        + ", ".join(str(path) for path in preprocess_locations)
                    )
            elif pipeline == "analysis_only":
                preprocessing_dirs = (
                    output / "cohort" / "preprocess",
                    results / "cohort" / "preprocess",
                )
                confound_dirs = (
                    output / "cohort" / "confound",
                    results / "cohort" / "confound",
                )
                if not any(
                    _workflow_path(path, "preprocess").is_file()
                    for path in preprocessing_dirs
                ):
                    raise ValueError(
                        "Cohort preprocessing output is missing. Run "
                        "preprocessing first."
                    )
                confound_ready = any(
                    any(
                        path.is_file()
                        for path in (
                            confound_dir
                            / "confound_correction_datasink"
                            / "cleaned_timeseries"
                        ).rglob("*_cleaned.nii.gz")
                    )
                    for confound_dir in confound_dirs
                )
                if not confound_ready:
                    raise ValueError(
                        "Cohort confound-correction cleaned timeseries are "
                        "missing. Run confound correction first."
                    )
            script = generate_cohort_script(
                bids_dir,
                results,
                templates,
                image,
                preprocess_args=self.stage_args["Preprocessing"],
                confound_args=self.stage_args["Confound correction"],
                analysis_args=self.stage_args["Analysis"],
                pipeline=pipeline,
                fix_species=self.cohort_fix_species_selector.currentText(),
                subject_prefix=self.path_fields["subject_prefix"].text().strip(),
                output_dir=output,
                archive_outputs=self.archive_outputs.isChecked(),
                template_files=self.template_files,
            )
            script_path = output / "tmp_script" / pipeline / "scrip_cohort.sh"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(script, encoding="utf-8")
            script_path.chmod(0o755)
            _log_generated_script(script_path, script)
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not create cohort script", str(error))
            logger.exception("Could not create cohort script")
            return
        self.status.setText(
            f"Created {pipeline_label} cohort script for {len(subjects)} "
            f"subject(s) in {script_path.parent}."
        )
        QMessageBox.information(
            self,
            "Cohort script created",
            f"Created {pipeline_label.lower()} cohort script for "
            f"{len(subjects)} subject(s): {script_path}",
        )

    def submit_cohort_script(self) -> None:
        _, output, results, _, _ = self._project_paths()
        bids_dir = self._selected_bids_dir()
        if bids_dir is None or not bids_dir.is_dir():
            QMessageBox.critical(
                self,
                "Original BIDS folder not set",
                "Select an existing original BIDS folder before submitting jobs.",
            )
            return
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(
                self, "Output directory not set",
                "Select a project root or set an output directory.",
            )
            return
        if not self.path_fields["results"].text().strip():
            QMessageBox.critical(
                self, "Results directory not set",
                "Select a project root or set a results directory.",
            )
            return
        pipeline = self.cohort_pipeline_selector.currentData()
        pipeline_label = self.cohort_pipeline_selector.currentText()
        subject_prefix = self.path_fields["subject_prefix"].text().strip()
        try:
            subjects = discover_subjects(bids_dir, subject_prefix)
            if not subjects:
                raise ValueError(f"No BIDS subjects found in {bids_dir}.")
            subject_names = [subject for subject, _, _ in subjects]
            orientation_issues = nifti_orientation_issues(
                bids_dir, subject_names
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "Could not check BIDS inputs", str(error))
            return
        if orientation_issues:
            QMessageBox.critical(
                self,
                "NIfTI orientation check failed",
                "Jobs cannot be submitted unless every RABIES-relevant BIDS "
                "NIfTI is readable and in RAS orientation. Scripts may still "
                "be created for inspection.\n\n" + "\n".join(orientation_issues),
            )
            return
        script_path = output / "tmp_script" / pipeline / "scrip_cohort.sh"
        if not script_path.is_file():
            QMessageBox.critical(
                self, "Cohort script not found",
                "Create the cohort script first.",
            )
            return
        try:
            script_text = script_path.read_text(encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Could not read cohort script", str(error))
            return
        resolved_bids = bids_dir.expanduser().resolve()
        expected_bids_source = (
            f"bids_source={shlex.quote(str(resolved_bids))}"
        )
        expected_bids_bind = "-B " + shlex.quote(
            f"{resolved_bids}:/input_bids:ro"
        )
        expected_cohort_dir = (
            f"cohort={shlex.quote(str((output / 'cohort').expanduser().resolve()))}"
        )
        expected_archive_dir = (
            "cohort_archive="
            + shlex.quote(str((results / "cohort").expanduser().resolve()))
        )
        if not all(
            required in script_text
            for required in (
                expected_bids_source,
                expected_bids_bind,
                expected_cohort_dir,
                expected_archive_dir,
            )
        ):
            QMessageBox.critical(
                self,
                "Cohort script is out of date",
                "The script is outdated or was created for a different BIDS "
                "folder. Create it again before submitting.",
            )
            return
        confirmation = QMessageBox.question(
            self,
            "Submit cohort job",
            f"Submit one {pipeline_label.lower()} job for all "
            f"{len(subject_names)} subject(s) in {bids_dir} with sbatch? "
            "RABIES reads the original BIDS directory read-only. The script "
            "uses the Archiving setting selected when it was created.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return
        command = ["sbatch", str(script_path)]
        logger.info("Executing command: %s", shlex.join(command))
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as error:
            details = getattr(error, "stderr", None) or str(error)
            logger.exception("Cohort sbatch submission failed")
            if getattr(error, "stdout", None):
                logger.info("sbatch stdout:\n%s", error.stdout)
            if getattr(error, "stderr", None):
                logger.error("sbatch stderr:\n%s", error.stderr)
            QMessageBox.critical(
                self, "Submission failed",
                f"Could not submit the cohort job.\n{details}",
            )
            return
        logger.info("sbatch stdout:\n%s", result.stdout.strip())
        if result.stderr.strip():
            logger.info("sbatch stderr:\n%s", result.stderr.strip())
        submitted = result.stdout.strip() or str(script_path)
        self.status.setText("Submitted one cohort job with sbatch.")
        QMessageBox.information(self, "Cohort job submitted", submitted)

    def remove_cohort_scripts(self) -> None:
        output_value = self.path_fields["output"].text().strip()
        if not output_value:
            QMessageBox.critical(
                self, "Output directory not set",
                "Choose a project root or set an output directory.",
            )
            return
        script_root = Path(output_value).expanduser() / "tmp_script"
        paths = [
            script_root / variant / "scrip_cohort.sh"
            for _, variant in COHORT_PIPELINE_VARIANTS
        ]
        paths.append(script_root / "scrip_cohort.sh")
        existing = [path for path in paths if path.is_file()]
        if not existing:
            QMessageBox.information(self, "No scripts found", "No cohort scripts exist.")
            return
        answer = QMessageBox.question(
            self,
            "Remove cohort scripts",
            f"Remove all {len(existing)} generated cohort script(s)? "
            "This does not remove processing outputs.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            for path in existing:
                path.unlink()
        except OSError as error:
            QMessageBox.critical(self, "Could not remove cohort scripts", str(error))
            return
        self.status.setText(f"Removed {len(existing)} generated cohort script(s).")

    def clear_cohort_outputs(self) -> None:
        output_value = self.path_fields["output"].text().strip()
        if not output_value:
            QMessageBox.critical(
                self, "Output directory not set",
                "Choose a project root or set an output directory.",
            )
            return
        output = Path(output_value).expanduser()
        target = output / "cohort"
        if not target.exists() and not target.is_symlink():
            QMessageBox.information(
                self, "No cohort working output",
                f"No temporary cohort output was found in {target}.",
            )
            return
        answer = QMessageBox.question(
            self,
            "Clear cohort working output",
            f"Permanently delete temporary cohort output from {target}?\n"
            "Archived results and generated scripts are not removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            removed = clear_cohort_output(output)
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self, "Could not clear cohort working output", str(error)
            )
            return
        self._refresh_cohort_status()
        self.status.setText(
            f"Removed {removed} cohort working output folder(s) from {target}."
        )

    def create_scripts(self) -> None:
        pipeline = self.pipeline_selector.currentData()
        pipeline_label = self.pipeline_selector.currentText()
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
        project_root, output, results, templates, image = self._project_paths()
        if not bids_dir.is_dir():
            QMessageBox.critical(
                self, "Original BIDS folder not found",
                f"Select an existing original BIDS folder (og_folder): {bids_dir}",
            )
            return
        if not self.path_fields["output"].text().strip():
            QMessageBox.critical(self, "Output directory not set", "Select a project root or set an output directory.")
            return
        if (
            pipeline != "fixrabies_prepare_only"
            and not self.path_fields["results"].text().strip()
        ):
            QMessageBox.critical(self, "Results directory not set", "Select a project root or set a results directory.")
            return
        if pipeline != "fixrabies_prepare_only":
            if not templates.is_dir():
                QMessageBox.critical(self, "Templates not found", f"Template directory does not exist: {templates}")
                return
            if not image.is_file():
                QMessageBox.critical(self, "RABIES image not found", f"Apptainer image does not exist: {image}")
                return
        fix_dir = None
        create_fix_dir = False
        if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
            if not project_root.is_dir():
                QMessageBox.critical(
                    self,
                    "Project folder not found",
                    f"Create or select an existing project folder before choosing a shared FIXRABIES directory: {project_root}",
                )
                return
            selected_fix_dir = self.fix_directory_selector.currentData()
            if selected_fix_dir == FIX_CREATE_NEW:
                folder_name = self.fix_directory_name.text().strip()
                if folder_name:
                    try:
                        folder_name = _validate_fix_directory_name(folder_name)
                    except ValueError as error:
                        QMessageBox.critical(self, "Invalid FIX folder name", str(error))
                        return
                    fix_dir = project_root / folder_name
                    if fix_dir.exists():
                        QMessageBox.critical(
                            self,
                            "FIX folder already exists",
                            f"Choose the existing folder from the FIX folder selector or enter another name: {fix_dir}",
                        )
                        return
                else:
                    fix_dir = suggested_fix_directory(project_root)
                create_fix_dir = True
            elif selected_fix_dir:
                fix_dir = Path(selected_fix_dir)
                if fix_dir not in list_fix_directories(project_root):
                    QMessageBox.critical(
                        self,
                        "FIXRABIES folder not found",
                        "The selected FIXRABIES folder no longer exists. Refresh subjects and select it again.",
                    )
                    return
            else:
                QMessageBox.critical(
                    self,
                    "FIXRABIES folder not selected",
                    "Choose a shared FIXRABIES folder.",
                )
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
                    session_name = _session_result_name(session)
                    if pipeline == "fixrabies_prepare_only":
                        preprocess_workflows = (
                            _workflow_path(
                                output / SINGLE_SUBJECT_OUTPUT_DIR
                                / "func_preprocess" / subject / session_name,
                                "preprocess",
                            ),
                            _workflow_path(_subject_archive_stage(
                                results, "func_preprocess", subject, session_name
                            ), "preprocess"),
                            _workflow_path(
                                results / subject / session_name / "preprocess",
                                "preprocess",
                            ),
                        )
                        if not any(path.is_file() for path in preprocess_workflows):
                            raise ValueError(
                                f"Preprocessing output is missing for "
                                f"{subject}/{session}. Checked: "
                                f"{', '.join(str(path) for path in preprocess_workflows)}. "
                                "Run preprocessing first."
                            )
                    elif pipeline == "analysis_only":
                        session_results = results / subject / session_name
                        archived_preprocess = _subject_archive_stage(
                            results, "func_preprocess", subject, session_name
                        )
                        archived_confound = _subject_archive_stage(
                            results, "func_confound", subject, session_name
                        )
                        archived_input_bids = _subject_archive_stage(
                            results, "tmp_bids_session", subject, session_name
                        )
                        if self.archive_outputs.isChecked():
                            preprocess_sources = (
                                archived_preprocess,
                                session_results / "preprocess",
                            )
                            confound_sources = (
                                archived_confound,
                                session_results / "confound",
                            )
                            input_available = (
                                archived_input_bids.is_dir()
                                or (session_results / "input_bids").is_dir()
                            )
                        else:
                            session_output = output / SINGLE_SUBJECT_OUTPUT_DIR
                            preprocess_sources = (
                                session_output / "func_preprocess" / subject
                                / session_name,
                                archived_preprocess,
                                session_results / "preprocess",
                            )
                            confound_sources = (
                                session_output / "func_confound" / subject
                                / session_name,
                                archived_confound,
                                session_results / "confound",
                            )
                            input_available = True
                        if not any(
                            _workflow_path(source, "preprocess").is_file()
                            for source in preprocess_sources
                        ) or not input_available:
                            raise ValueError(
                                f"Preprocessing and BIDS inputs are missing "
                                f"for {subject}/{session}. Run a "
                                "preprocessing workflow first."
                            )
                        confound_ready = any(
                            _workflow_path(
                                source, "confound_correction"
                            ).is_file()
                            and any(
                                path.is_file()
                                for path in (
                                    source
                                    / "confound_correction_datasink"
                                    / "cleaned_timeseries"
                                ).rglob("*_cleaned.nii.gz")
                            )
                            for source in confound_sources
                        )
                        if not confound_ready:
                            raise ValueError(
                                f"Confound cleaned timeseries are missing for "
                                f"{subject}/{session}. Run confound correction "
                                "first."
                            )
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
                        archive_outputs=self.archive_outputs.isChecked(),
                        session=session,
                        pipeline=pipeline,
                        fix_species=self.fix_species_selector.currentText(),
                        fix_dir=fix_dir,
                        template_files=self.template_files,
                    )
                    scripts.append((
                        script_dir / pipeline / f"scrip_{subject}_{session_name}.sh",
                        script,
                    ))
            if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
                assert fix_dir is not None
                if create_fix_dir:
                    fix_dir.mkdir()
                record_fix_subjects(
                    fix_dir, selected, self.fix_species_selector.currentText()
                )
            for script_path, script in scripts:
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text(script, encoding="utf-8")
                script_path.chmod(0o755)
                _log_generated_script(script_path, script)
            if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
                for row in range(self.subjects.rowCount()):
                    subject_item = self.subjects.item(row, 0)
                    if subject_item is None or subject_item.text() not in selected:
                        continue
                    assigned_dirs = fix_directories_for_subject(
                        project_root, subject_item.text()
                    )
                    folder_item = QTableWidgetItem(
                        ", ".join(path.name for path in assigned_dirs) or "—"
                    )
                    if assigned_dirs:
                        folder_item.setToolTip(
                            "\n".join(str(path) for path in assigned_dirs)
                        )
                    self.subjects.setItem(row, 7, folder_item)
                self._refresh_fix_directory_options(project_root)
                if create_fix_dir:
                    self.fix_directory_name.clear()
                selected_fix_index = self.fix_directory_selector.findData(
                    str(fix_dir)
                )
                if selected_fix_index >= 0:
                    self.fix_directory_selector.setCurrentIndex(
                        selected_fix_index
                    )
        except (OSError, ValueError, KeyError) as error:
            QMessageBox.critical(self, "Could not create scripts", str(error))
            logger.exception("Could not create session scripts")
            return
        self.status.setText(
            f"Created {pipeline_label} scripts for {len(selected)} subject(s) "
            f"in {script_dir / pipeline}"
            + (f" using {fix_dir}." if fix_dir is not None else ".")
        )
        QMessageBox.information(
            self, "Session scripts created",
            f"Created {len(scripts)} {pipeline_label.lower()} session script(s) "
            f"in {script_dir / pipeline}."
            + (f"\nShared FIXRABIES folder: {fix_dir}" if fix_dir is not None else ""),
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
        pipeline = self.pipeline_selector.currentData()
        pipeline_label = self.pipeline_selector.currentText()
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
        if (
            pipeline != "fixrabies_prepare_only"
            and not self.path_fields["results"].text().strip()
        ):
            QMessageBox.critical(self, "Results directory not set", "Select a project root or set a results directory.")
            return
        session_filter = (
            {selected[0]: set(selected_session_names)}
            if selected_session_names
            else None
        )
        if pipeline == "fixrabies_prepare_only":
            orientation_issues = []
        else:
            try:
                orientation_issues = nifti_orientation_issues(
                    bids_dir, selected, session_filter
                )
            except OSError as error:
                QMessageBox.critical(
                    self, "Could not check NIfTI orientations", str(error)
                )
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
                    output / "tmp_script" / pipeline
                    / f"scrip_{subject}_{session_name}.sh"
                )
                if not script_path.is_file():
                    missing.append(str(script_path))
                    continue
                try:
                    fix_dir = (
                        fix_directory_from_script(script_path)
                        if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}
                        else None
                    )
                except (OSError, ValueError) as error:
                    missing.append(f"{script_path}: {error}")
                    continue
                if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"} and fix_dir is None:
                    missing.append(
                        f"{script_path}: no shared FIXRABIES directory is configured"
                    )
                    continue
                if pipeline_has_previous_results(
                    subject, results, session, pipeline, fix_dir
                ):
                    blocked_sessions.append(f"{subject}/{session}")
                else:
                    script_paths.append(script_path)
        if not script_paths and blocked_sessions:
            if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}:
                explanation = (
                    "No session jobs can be submitted because prepared scan data "
                    "already exists in the shared FIXRABIES folder for:\n"
                    + "\n".join(blocked_sessions)
                    + "\nChoose a different FIX folder if you intend to prepare a separate copy."
                )
            else:
                explanation = (
                    "No session jobs can be submitted because archived results already "
                    "exist for the selected sessions:\n"
                    + "\n".join(blocked_sessions)
                    + "\nSelect those sessions and choose Clear selected session results to rerun them."
                )
            QMessageBox.critical(
                self,
                "FIXRABIES scans already prepared"
                if pipeline in {"fixrabies_prepare", "fixrabies_prepare_only"}
                else "Session results must be cleared",
                explanation,
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
            f"Submit {len(script_paths)} {pipeline_label.lower()} session job(s) "
            "to SLURM with sbatch?"
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
                command = ["sbatch", str(path)]
                logger.info("Executing command: %s", shlex.join(command))
                result = subprocess.run(
                    command, check=True, capture_output=True, text=True
                )
                logger.info("sbatch stdout:\n%s", result.stdout.strip())
                if result.stderr.strip():
                    logger.info("sbatch stderr:\n%s", result.stderr.strip())
                submitted.append(result.stdout.strip() or str(path))
        except (OSError, subprocess.CalledProcessError) as error:
            details = getattr(error, "stderr", None) or str(error)
            logger.exception("Session sbatch submission failed")
            if getattr(error, "stdout", None):
                logger.info("sbatch stdout:\n%s", error.stdout)
            if getattr(error, "stderr", None):
                logger.error("sbatch stderr:\n%s", error.stderr)
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


def _configure_terminal_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def main_subject_manager() -> None:
    _configure_terminal_logging()
    logger.info(
        "Starting RABIES GUI with Python %s from %s (working directory: %s)",
        sys.version.split()[0],
        sys.executable,
        Path.cwd(),
    )
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)
    app = QApplication([])
    configure_dark_mode(app)
    splash_pixmap = QPixmap(str(SPLASH_IMAGE))
    splash: QSplashScreen | None = None
    if not splash_pixmap.isNull():
        splash_pixmap = splash_pixmap.scaled(
            640,
            480,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        splash_screen = QSplashScreen(
            splash_pixmap, Qt.WindowType.WindowStaysOnTopHint
        )
        splash_screen.show()
        splash = splash_screen
        app.processEvents()

    window = ProjectSetupWindow()
    if splash is not None:
        splash_screen = splash

        def show_main_window() -> None:
            window.show()
            splash_screen.finish(window)

        QTimer.singleShot(3000, show_main_window)
    else:
        window.show()
    app.exec()


def main() -> None:
    main_subject_manager()


if __name__ == "__main__":
    main()
