# Manage subjects with the GUI

`rabies_subject_manager.py` is a PySide6 application for viewing BIDS
subjects, checking NIfTI orientations and completed RABIES stages, and creating
or submitting one SLURM job script per selected subject.

Run the GUI in a Linux desktop or X11-forwarded session that can access the
BIDS, output, and results directories. To submit jobs from the GUI, that
system must also have `sbatch` available. For example:

```sh
python -m pip install -r scripts/rabies_gui_requirements.txt
python scripts/rabies_subject_manager.py
```

The GUI opens in the **RABIES Project Setup** window. Browse to the project
root, output directory, results directory, RABIES image, and template folder
(rat, mouse, or custom). Choosing a project root fills the output and results
paths with `<project root>/rabies_output/` and
`<project root>/rabies_results/`; edit those fields afterward if needed.

Set **Subject folder prefix** to the leading text shared by subject directory
names. It defaults to `sub-` (for example, `sub-001`); change it to `mouse-`,
`participant-`, or the appropriate prefix for your dataset. This setting
filters both the BIDS-folder dropdown and the subjects shown in the manager.
The prefix must not be empty or contain path separators.

Choose the original BIDS folder from the dropdown, which lists direct
subfolders of the project root containing folders matching the subject prefix,
or use its **Browse…** button to select another BIDS folder. The BIDS folder
does not have to be named `og_bids`. Select **Open subject manager** to move
to the separate subject window. Use **Project setup…** there to return to the
setup window and apply different paths.

The subject window contains the subject table, stage status, script controls,
cleanup actions, and cleaned-timeseries tools. It shows BOLD and T2w scan
counts and the status of preprocessing, confound correction, and analysis.
Select a subject to view its sessions, every NIfTI's orientation, whether the
session input archive is present, and the subject-wide stage results. Script
creation is allowed regardless of orientation, but job submission is blocked
if any BIDS NIfTI is unreadable or is not in RAS orientation.

Stage status is based on the corresponding
`rabies_<stage>_workflow.pkl` file. RABIES writes this workflow pickle after a
stage completes. The GUI also recognizes archived workflow pickles in the
results directory. For compatibility with results from the older script, it
also recognizes its nested `analysis/<subject>/rabies_analysis.pkl` file.

Select one or more rows and choose **Create scripts** to write
`<output directory>/tmp_script/scrip_<subject>.sh`. This does not start
processing. Choose **Submit scripts with sbatch** separately to submit the
selected scripts. The generated job runs only stages without a completion
pickle, using RABIES `--force` only for those incomplete stages so interrupted
stages can be retried. It archives the stage logs along with the confound
datasink, workflow pickle, and CLI-options pickle before cleaning the temporary
confound directory, then restores the confound files if analysis is run later.
If an older archive lacks the CLI-options pickle, the job reruns confound
correction to recreate it. Preprocessing outputs remain in the output directory
so later stages can use them.

The **Analysis** status displays **Existing output (clear to rerun)** when a
subject already has archived results. The GUI will not create or submit a job
for that subject until its results are cleared, and generated scripts also
check for existing results before starting. Use **Clear selected results** to
remove archived items only for selected subjects, or **Clear ALL results** to
remove every item inside the results directory, including shared cleaned
timeseries. Both actions require confirmation and leave the results directory
itself in place. Shared cleaned-timeseries files still block the matching
subject; use **Clear ALL results** to remove those shared files.

Use **Clear selected output** to remove only selected subjects' temporary
workflow folders from `rabies_output`, or **Clear ALL subject output** to clear
those folders for every subject found there. These actions remove per-subject
temporary BIDS copies and preprocessing, confound-correction, and analysis
folders, while preserving generated scripts and other shared files. They do
not remove archived results from `rabies_results`; clear those separately if
you intend to rerun analysis.

Choose **RABIES arguments…** to edit the command-line options for each of the
three stages. The editors start with the options used by the original batch
script; changes are applied to scripts created while the GUI is open. Enter
arguments in RABIES CLI form without the stage name or input/output paths.
Braced dictionary values are supported, for example
`--scan_QC_thresholds '{DR:{Dice:[0.3]}}'`.

**Remove selected scripts** deletes only the selected subjects'
`scrip_<subject>.sh` files from `tmp_script/`; it does not delete processing
outputs. Then use **Create scripts** to generate them again with the current
arguments.

Select subjects and choose **Move cleaned timeseries** to move their
`*_cleaned.nii.gz` files from
`<results>/<subject>/confound/confound_correction_datasink/cleaned_timeseries/`
into the shared `<results>/cleaned_timeseries/` folder. This action moves
files (it does not copy them), keeps their filenames, and skips files when a
destination with the same name already exists.

Each generated job expects per-subject `*_bold.nii.gz` and `*_T2w.nii.gz`
files and RABIES 0.6.3. The default stage arguments use the SIGMA rat template
layout. When selecting mouse or custom templates, use **RABIES arguments…** in
the subject window to set the corresponding template and atlas file paths, and
review the generated scripts before submission.

# Setting up the work environment

## Organizing the template folder

The selected template-folder path is bind-mounted inside each Apptainer job as
`/templates`. The default GUI arguments expect the SIGMA rat template files in
this layout:

```text
rat_templates/
├── anatomy/
│   ├── SIGMA_InVivo_Brain_Template.nii.gz
│   ├── SIGMA_InVivo_Brain_Mask.nii.gz
│   ├── SIGMA_InVivo_WM_bin.nii.gz
│   └── SIGMA_InVivo_CSF_bin.nii.gz
├── atlas/
│   └── SIGMA_Anatomical_Brain_Atlas.nii.gz
└── canica_resting_state.nii.gz
```

For example, selecting `/project/templates/rat_templates` makes
`/project/templates/rat_templates/anatomy/SIGMA_InVivo_Brain_Template.nii.gz`
available to the container as
`/templates/anatomy/SIGMA_InVivo_Brain_Template.nii.gz`. Keep the expected
relative paths and filenames, or edit the corresponding paths in
**RABIES arguments…** before creating scripts.

Mouse and custom templates can use a different organization. Select their
containing folder in Project Setup, then update the preprocessing arguments
(`--anat_template`, `--brain_mask`, `--WM_mask`, `--CSF_mask`, and
`--vascular_mask`) and analysis arguments (`--ROI_labels_file` and
`--prior_maps`) to point to the files in that folder. Those paths are resolved
inside the container, so use `/templates/...` paths in the argument editor.