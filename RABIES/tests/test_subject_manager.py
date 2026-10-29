import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import nibabel as nib
import numpy as np
from PySide6.QtWidgets import QApplication

from scripts.rabies_subject_manager import (
    ProjectSetupWindow,
    SubjectManager,
    _expand_template_paths,
    clear_results,
    discover_bids_folders,
    discover_subjects,
    generate_subject_script,
    nifti_orientation,
    nifti_orientation_issues,
    move_cleaned_timeseries,
    clear_output_subjects,
    output_subject_names,
    session_nifti_orientations,
    stage_status,
    subject_has_previous_results,
)


class SubjectManagerTests(unittest.TestCase):
    def test_discovers_subject_scan_counts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bids = root / "og_bids"
            subject = bids / "sub-001"
            (subject / "ses-1" / "func").mkdir(parents=True)
            (subject / "ses-1" / "anat").mkdir(parents=True)
            (subject / "ses-1" / "func" / "sub-001_task-rest_bold.nii.gz").touch()
            (subject / "ses-1" / "anat" / "sub-001_T2w.nii.gz").touch()
            (subject / "ses-2" / "func").mkdir(parents=True)
            (subject / "ses-2" / "anat").mkdir(parents=True)
            (subject / "ses-2" / "func" / "sub-001_ses-2_task-rest_bold.nii.gz").touch()
            (subject / "ses-2" / "anat" / "sub-001_ses-2_T2w.nii.gz").touch()
            (bids / "not-a-subject").mkdir()

            self.assertEqual(discover_subjects(bids), [("sub-001", 2, 2)])

    def test_subjects_can_be_discovered_from_arbitrarily_named_bids_folder(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bids = root / "raw_data"
            subject = bids / "sub-002"
            (subject / "func").mkdir(parents=True)
            (subject / "func" / "sub-002_bold.nii.gz").touch()

            self.assertEqual(
                discover_subjects(bids),
                [("sub-002", 1, 0)],
            )

    def test_subject_prefix_can_be_changed_for_subject_and_bids_folder_discovery(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bids = root / "raw_data"
            subject = bids / "mouse-001"
            (subject / "func").mkdir(parents=True)
            (subject / "func" / "mouse-001_bold.nii.gz").touch()
            (bids / "sub-ignored").mkdir()

            self.assertEqual(
                discover_subjects(bids, "mouse-"),
                [("mouse-001", 1, 0)],
            )
            self.assertEqual(discover_bids_folders(root, "mouse-"), [bids])

    def test_subject_prefix_must_be_a_nonempty_folder_prefix(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            for prefix in ("", ".", "..", "sub/"):
                with self.subTest(prefix=prefix):
                    with self.assertRaises(ValueError):
                        discover_subjects(root, prefix)

    def test_nifti_orientations_are_reported_for_each_session(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            subject_dir = Path(temporary_directory) / "sub-001"
            ras_file = subject_dir / "ses-1" / "anat" / "sub-001_ses-1_T2w.nii.gz"
            lps_file = subject_dir / "ses-2" / "func" / "sub-001_ses-2_bold.nii.gz"
            ras_file.parent.mkdir(parents=True)
            lps_file.parent.mkdir(parents=True)
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2)), np.eye(4)),
                str(ras_file),
            )
            lps_affine = np.diag([-1, -1, 1, 1])
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2)), lps_affine),
                str(lps_file),
            )

            sessions = session_nifti_orientations(subject_dir)

            self.assertEqual(list(sessions), ["ses-1", "ses-2"])
            self.assertEqual(sessions["ses-1"], [(ras_file, "RAS")])
            self.assertEqual(sessions["ses-2"], [(lps_file, "LPS")])
            self.assertEqual(nifti_orientation(ras_file), "RAS")
            issues = nifti_orientation_issues(subject_dir.parent, ["sub-001"])
            self.assertEqual(
                issues,
                ["sub-001/ses-2/func/sub-001_ses-2_bold.nii.gz: LPS"],
            )

    def test_unreadable_niftis_and_subjects_without_niftis_block_submission(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            bids_dir = Path(temporary_directory)
            subject_dir = bids_dir / "sub-001"
            (subject_dir / "ses-1").mkdir(parents=True)
            (subject_dir / "ses-1" / "invalid.nii.gz").write_bytes(b"not a NIfTI")
            (bids_dir / "sub-002").mkdir()

            issues = nifti_orientation_issues(bids_dir, ["sub-001", "sub-002"])

            self.assertIn("sub-001/ses-1/invalid.nii.gz: Unreadable:", issues[0])
            self.assertEqual(issues[1], "sub-002: no NIfTI files found.")

    def test_selecting_subject_shows_session_orientations_and_results(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bids_dir = root / "og_bids"
            subject_dir = bids_dir / "sub-001"
            for session, affine in (
                ("ses-1", np.eye(4)),
                ("ses-2", np.diag([-1, -1, 1, 1])),
            ):
                nifti = (
                    subject_dir / session / "func"
                    / f"sub-001_{session}_task-rest_bold.nii.gz"
                )
                nifti.parent.mkdir(parents=True)
                nib.save(nib.Nifti1Image(np.zeros((2, 2, 2)), affine), str(nifti))
            (root / "rabies_output").mkdir()
            archived_session = root / "rabies_results" / "sub-001" / "ses-1"
            archived_session.mkdir(parents=True)
            preprocess_archive = (
                root / "rabies_results" / "sub-001" / "preprocess"
            )
            preprocess_archive.mkdir(parents=True)
            (preprocess_archive / "rabies_preprocess_workflow.pkl").touch()

            setup = ProjectSetupWindow()
            setup.path_fields["root"].setText(str(root))
            setup.path_fields["output"].setText(str(root / "rabies_output"))
            setup.path_fields["results"].setText(str(root / "rabies_results"))
            bids_index = setup.bids_folders.findData(str(bids_dir))
            setup.bids_folders.setCurrentIndex(bids_index)
            manager = SubjectManager(setup)
            try:
                manager.subjects.setCurrentCell(0, 0)

                self.assertEqual(manager.session_details.rowCount(), 2)
                self.assertEqual(manager.session_details.item(0, 0).text(), "ses-1")
                self.assertIn("RAS", manager.session_details.item(0, 1).text())
                self.assertEqual(manager.session_details.item(0, 2).text(), "Present")
                self.assertEqual(manager.session_details.item(0, 3).text(), "Complete")
                self.assertEqual(manager.session_details.item(1, 0).text(), "ses-2")
                self.assertIn("LPS", manager.session_details.item(1, 1).text())
            finally:
                manager.close()
                setup.close()
                app.processEvents()

    def test_non_ras_subject_can_create_scripts_but_cannot_submit(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bids_dir = root / "og_bids"
            subject_dir = bids_dir / "sub-001" / "ses-1"
            bold_file = subject_dir / "func" / "sub-001_ses-1_task-rest_bold.nii.gz"
            anat_file = subject_dir / "anat" / "sub-001_ses-1_T2w.nii.gz"
            bold_file.parent.mkdir(parents=True)
            anat_file.parent.mkdir(parents=True)
            lps_affine = np.diag([-1, -1, 1, 1])
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2)), lps_affine),
                str(bold_file),
            )
            nib.save(
                nib.Nifti1Image(np.zeros((2, 2, 2)), np.eye(4)),
                str(anat_file),
            )
            output = root / "rabies_output"
            templates = root / "templates"
            output.mkdir()
            templates.mkdir()
            image = root / "rabies.sif"
            image.touch()

            setup = ProjectSetupWindow()
            setup.path_fields["root"].setText(str(root))
            setup.path_fields["output"].setText(str(output))
            setup.path_fields["results"].setText(str(root / "rabies_results"))
            setup.path_fields["templates"].setText(str(templates))
            setup.path_fields["image"].setText(str(image))
            setup.bids_folders.setCurrentIndex(
                setup.bids_folders.findData(str(bids_dir))
            )
            manager = SubjectManager(setup)
            try:
                manager.subjects.selectRow(0)
                script_path = output / "tmp_script" / "scrip_sub-001.sh"
                with patch("scripts.rabies_subject_manager.QMessageBox.information"):
                    manager.create_scripts()
                self.assertTrue(script_path.is_file())

                with patch(
                    "scripts.rabies_subject_manager.QMessageBox.critical"
                ) as show_error, patch(
                    "scripts.rabies_subject_manager.subprocess.run"
                ) as submit:
                    manager.submit_scripts()

                show_error.assert_called_once()
                self.assertEqual(show_error.call_args.args[1], "NIfTI orientation check failed")
                self.assertIn("LPS", show_error.call_args.args[2])
                submit.assert_not_called()
            finally:
                manager.close()
                setup.close()
                app.processEvents()

    def test_root_folder_choices_only_include_directories_with_subjects(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "og_bids"
            (source / "sub-001").mkdir(parents=True)
            (root / "rabies_output").mkdir()
            (root / "nested" / "folder" / "sub-002").mkdir(parents=True)

            self.assertEqual(discover_bids_folders(root), [source])

    def test_move_cleaned_timeseries_collects_selected_subject_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            results = Path(temporary_directory) / "rabies_results"
            source = (
                results
                / "sub-RICK493409"
                / "confound"
                / "confound_correction_datasink"
                / "cleaned_timeseries"
                / "_split_name_sub-RICK493409_task-rsn_bold"
                / "sub-RICK493409_task-rsn_bold_cleaned.nii.gz"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"cleaned data")

            moved, skipped = move_cleaned_timeseries(["sub-RICK493409"], results)

            destination = (
                results
                / "cleaned_timeseries"
                / "sub-RICK493409_task-rsn_bold_cleaned.nii.gz"
            )
            self.assertEqual(moved, [destination])
            self.assertEqual(skipped, [])
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_bytes(), b"cleaned data")

    def test_move_cleaned_timeseries_skips_existing_destination_names(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            results = Path(temporary_directory) / "rabies_results"
            source = (
                results / "sub-001" / "confound" / "confound_correction_datasink"
                / "cleaned_timeseries" / "_split_name_sub-001" / "sub-001_bold_cleaned.nii.gz"
            )
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            destination = results / "cleaned_timeseries" / source.name
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"existing")

            moved, skipped = move_cleaned_timeseries(["sub-001"], results)

            self.assertEqual(moved, [])
            self.assertEqual(skipped, [source])
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"existing")

    def test_selected_results_can_be_cleared_without_removing_other_subjects(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            results = Path(temporary_directory) / "rabies_results"
            selected = results / "sub-001" / "analysis"
            other = results / "sub-002" / "analysis"
            selected.mkdir(parents=True)
            other.mkdir(parents=True)
            (selected / "output.txt").touch()
            (other / "output.txt").touch()

            self.assertTrue(subject_has_previous_results("sub-001", results))
            self.assertEqual(clear_results(results, ["sub-001"]), 1)

            self.assertFalse(subject_has_previous_results("sub-001", results))
            self.assertTrue(subject_has_previous_results("sub-002", results))
            self.assertTrue((other / "output.txt").is_file())
            self.assertTrue(results.is_dir())

    def test_all_results_can_be_cleared_without_removing_results_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            results = Path(temporary_directory) / "rabies_results"
            (results / "sub-001" / "analysis").mkdir(parents=True)
            (results / "cleaned_timeseries").mkdir()

            self.assertEqual(clear_results(results), 2)

            self.assertTrue(results.is_dir())
            self.assertEqual(list(results.iterdir()), [])

    def test_shared_cleaned_timeseries_blocks_matching_subject(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            results = Path(temporary_directory) / "rabies_results"
            cleaned = results / "cleaned_timeseries"
            cleaned.mkdir(parents=True)
            (cleaned / "sub-001_task-rest_cleaned.nii.gz").touch()

            self.assertTrue(subject_has_previous_results("sub-001", results))
            self.assertFalse(subject_has_previous_results("sub-002", results))

    def test_results_cleanup_rejects_protected_directories(self):
        repository_root = Path(__file__).resolve().parents[1]

        with self.assertRaises(ValueError):
            clear_results(repository_root)

    def test_selected_subject_output_can_be_cleared_without_shared_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rabies_output"
            selected = output / "func_preprocess" / "sub-001"
            other = output / "func_confound" / "sub-002"
            selected.mkdir(parents=True)
            other.mkdir(parents=True)
            (selected / "workflow.dat").touch()
            (other / "workflow.dat").touch()
            scripts = output / "tmp_script"
            scripts.mkdir()
            (scripts / "scrip_sub-001.sh").touch()
            shared = output / "shared_file.txt"
            shared.touch()

            self.assertEqual(clear_output_subjects(output, ["sub-001"]), 1)

            self.assertFalse(selected.exists())
            self.assertTrue((other / "workflow.dat").is_file())
            self.assertTrue((scripts / "scrip_sub-001.sh").is_file())
            self.assertTrue(shared.is_file())

    def test_all_subject_output_can_be_cleared_while_preserving_shared_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "rabies_output"
            (output / "tmp_bids" / "sub-001").mkdir(parents=True)
            (output / "func_analysis" / "sub-002").mkdir(parents=True)
            (output / "tmp_script").mkdir()
            (output / "tmp_script" / "scrip_sub-001.sh").touch()

            self.assertEqual(output_subject_names(output), {"sub-001", "sub-002"})
            self.assertEqual(clear_output_subjects(output), 2)

            self.assertEqual(output_subject_names(output), set())
            self.assertTrue((output / "tmp_script" / "scrip_sub-001.sh").is_file())

    def test_output_cleanup_rejects_protected_directories(self):
        repository_root = Path(__file__).resolve().parents[1]

        with self.assertRaises(ValueError):
            clear_output_subjects(repository_root)

    def test_only_completed_workflow_pickles_mark_stages_complete(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output = root / "output"
            results = root / "results"
            (output / "func_preprocess" / "sub-001").mkdir(parents=True)
            (output / "func_preprocess" / "sub-001" / "rabies_preprocess.pkl").touch()
            (results / "sub-001" / "analysis").mkdir(parents=True)
            (results / "sub-001" / "analysis" / "rabies_analysis_workflow.pkl").touch()

            self.assertEqual(
                stage_status("sub-001", output, results),
                {"preprocess": False, "confound": False, "analysis": True},
            )
            (output / "func_preprocess" / "sub-001" / "rabies_preprocess_workflow.pkl").touch()
            (results / "sub-001" / "confound").mkdir(parents=True)
            (results / "sub-001" / "confound" / "rabies_confound_correction_workflow.pkl").touch()

            self.assertEqual(
                stage_status("sub-001", output, results),
                {"preprocess": True, "confound": True, "analysis": True},
            )
            legacy_analysis = results / "sub-legacy" / "analysis" / "sub-legacy"
            legacy_analysis.mkdir(parents=True)
            (legacy_analysis / "rabies_analysis.pkl").touch()
            self.assertTrue(stage_status("sub-legacy", output, results)["analysis"])

    def test_generated_script_is_resumable_and_archives_markers(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = generate_subject_script(
                "sub-001",
                [root / "input bold.nii.gz"],
                [root / "input T2w.nii.gz"],
                root / "output",
                root / "results",
                root / "templates",
                root / "rabies.sif",
            )

            self.assertIn("rabies_preprocess_workflow.pkl", script)
            self.assertIn("rabies_preprocess.log", script)
            self.assertIn("rabies_confound_correction_workflow.pkl", script)
            self.assertIn("rabies_confound_correction.pkl", script)
            self.assertIn("rabies_confound_correction.log", script)
            self.assertIn("rabies_analysis_workflow.pkl", script)
            self.assertIn('cp -a "$analysis/".', script)
            self.assertIn(
                f"result_subject={shlex.quote(str(root / 'results' / 'sub-001'))}",
                script,
            )
            self.assertIn("Refusing to analyze $subject: previous results exist", script)
            self.assertIn("Clear this subject's results in the GUI first.", script)
            self.assertIn(
                f"cp -f {shlex.quote(str(root / 'output' / 'func_confound' / 'sub-001' / 'rabies_confound_correction.pkl'))} "
                f"{shlex.quote(str(root / 'results' / 'sub-001' / 'confound'))}/",
                script,
            )
            self.assertIn(
                f"cp -f {shlex.quote(str(root / 'results' / 'sub-001' / 'confound' / 'rabies_confound_correction.pkl'))} "
                '"$confound/"',
                script,
            )
            self.assertIn(
                f"|| ! -f {shlex.quote(str(root / 'results' / 'sub-001' / 'confound' / 'rabies_confound_correction.pkl'))}",
                script,
            )
            self.assertIn(" -f ", script)
            self.assertIn("#SBATCH --time=12:00:00", script)
            self.assertIn("-B", script)
            self.assertIn("/templates/anatomy/SIGMA_InVivo_Brain_Template.nii.gz", script)
            self.assertIn("if [[ ! -f", script)
            self.assertIn("confound_correction_datasink", script)
            self.assertIn("input bold.nii.gz", script)
            self.assertIn(str(root / "input bold.nii.gz"), script)

    def test_generated_script_preserves_and_archives_each_bids_session(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            subject_dir = root / "og_bids" / "sub-001"
            bold_files = [
                subject_dir / "ses-1" / "func" / "sub-001_ses-1_bold.nii.gz",
                subject_dir / "ses-2" / "func" / "sub-001_ses-2_bold.nii.gz",
            ]
            anat_files = [
                subject_dir / "ses-1" / "anat" / "sub-001_ses-1_T2w.nii.gz",
                subject_dir / "ses-2" / "anat" / "sub-001_ses-2_T2w.nii.gz",
            ]

            script = generate_subject_script(
                "sub-001",
                bold_files,
                anat_files,
                root / "output",
                root / "results",
                root / "templates",
                root / "rabies.sif",
            )

            for session, modality, source in (
                ("ses-1", "func", bold_files[0]),
                ("ses-1", "anat", anat_files[0]),
                ("ses-2", "func", bold_files[1]),
                ("ses-2", "anat", anat_files[1]),
            ):
                staged_directory = root / "output" / "tmp_bids" / "sub-001" / session / modality
                self.assertIn(f"mkdir -p {shlex.quote(str(staged_directory))}", script)
                self.assertIn(
                    f"cp -f {shlex.quote(str(source))} {shlex.quote(str(staged_directory))}/",
                    script,
                )
                self.assertIn(
                    f"cp -a {shlex.quote(str(root / 'output' / 'tmp_bids' / 'sub-001' / session))} "
                    f"{shlex.quote(str(root / 'results' / 'sub-001'))}/",
                    script,
                )

    def test_custom_stage_arguments_are_used_and_json_braces_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            script = generate_subject_script(
                "sub-001",
                [root / "sub-001_bold.nii.gz"],
                [root / "sub-001_T2w.nii.gz"],
                root / "output",
                root / "results",
                root / "templates",
                root / "rabies.sif",
                preprocess_args="--TR 2 --anat_template {anat_template}",
                confound_args="--highpass 0.02",
                analysis_args="--scan_QC_thresholds '{DR:{Dice:[0.3]}}' --prior_maps {priors}",
            )

            self.assertIn("--TR 2", script)
            self.assertIn("--highpass 0.02", script)
            self.assertIn("{DR:{Dice:[0.3]}}", script)
            self.assertIn("/templates/canica_resting_state.nii.gz", script)

    def test_template_expansion_does_not_consume_other_braces(self):
        expanded = _expand_template_paths(
            "--anat_template {anat_template} --scan_QC_thresholds '{DR:{Dice:[0.3]}}'",
            {"anat_template": "/templates/rat.nii.gz"},
        )

        self.assertEqual(
            expanded,
            "--anat_template /templates/rat.nii.gz --scan_QC_thresholds '{DR:{Dice:[0.3]}}'",
        )


if __name__ == "__main__":
    unittest.main()
