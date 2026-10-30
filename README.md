# RABIES subject and cohort managers

Two PySide6 GUIs are available for viewing BIDS subjects, checking NIfTI
orientations, and creating or submitting RABIES SLURM jobs:

- `rabies_subject_manager.py` creates one independent job per BIDS session for
  selected subjects. Each job runs preprocessing, confound correction, and
  analysis for that session only.
- `rabies_cohort_manager.py` creates one cohort-wide job for the full selected
  BIDS dataset, using RABIES' native subject/session handling.

Run the GUI in a Linux desktop or X11-forwarded session that can access the
BIDS, output, and results directories. To submit jobs from the GUI, that
system must also have `sbatch` available. For example:

```sh
python -m pip install -r rabies_gui_requirements.txt
# One job per BIDS session for selected subjects
python rabies_subject_manager.py
# One cohort-wide job
python rabies_cohort_manager.py
```

Both managers use the same project setup and stage arguments. Their generated
scripts, workflow outputs, and archived stage results use separate paths;
both modes use the shared `cleaned_timeseries` folder when files are moved
there.

The GUI opens in the **RABIES Project Setup** window. Browse to the project
root, output directory, results directory, RABIES image, and template folder
(rat, mouse, or custom). Choosing a project root fills the output and results
paths with `<project root>/rabies_output/` and
`<project root>/rabies_results/`; edit those fields afterward if needed.
To show a splash image while the subject manager starts, place a `splash.png`
file beside `rabies_subject_manager.py`. The splash is optional; without that
file, the GUI starts normally.

The instructions below describe the cohort-wide manager,
`rabies_cohort_manager.py`. For independent per-session jobs, launch
`rabies_subject_manager.py` instead and create/submit scripts for the selected
subjects. It creates a separate `scrip_<subject>_<session>.sh` for each
session, stages only that session's BOLD/T2w files, and writes stage outputs
under `<output>/func_<stage>/<subject>/<session>/` and archived results under
`<results>/<subject>/<session>/`. In the per-session manager, select session
rows and choose **Clear selected session results** before submitting a session
again. With no session rows selected, **Submit scripts with sbatch** submits
eligible sessions for the selected subjects and skips sessions that already
have archived results. If session rows are selected, it submits only those
sessions for the current subject. Each session's analysis is independent; it
does not combine data across sessions or subjects for group ICA.

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
session input archive is present, and the applicable session or cohort stage
results. Script
creation is allowed regardless of orientation, but job submission is blocked
if any BIDS NIfTI is unreadable or is not in RAS orientation. Orientation
entries show a concise session/modality label; hover over an entry to see its
full path. Use **Reorient selected NIfTIs to RAS** to convert non-RAS files.
The GUI asks for confirmation, preserves originals in a timestamped
`<BIDS folder>_orientation_backups` directory beside the BIDS folder, and
replaces the input files with RAS-oriented copies. If a cohort input snapshot
already exists, clear all results before changing orientations so the archived
inputs and stage outputs cannot become inconsistent.

Stage status is based on the corresponding
`rabies_<stage>_workflow.pkl` file. RABIES writes this workflow pickle after a
stage completes. The three stage markers under
`<results directory>/cohort/{preprocess,confound,analysis}/` reflect progress
for the entire BIDS dataset and are shown for every subject row.

Choose **Create cohort script** to write
`<output directory>/tmp_script/scrip_cohort.sh`, then choose **Submit cohort
with sbatch** to submit one job for every subject and session in the selected
BIDS folder. Selection in the subject table is only for viewing subject
details and reorienting selected files; it does not narrow the analysis cohort.
The script preserves the complete BIDS tree in the cohort archive, then passes
that archived BIDS root to RABIES, which discovers and pairs subject/session
scans using its native BIDS handling. Its `MultiProc` workflows
run preprocessing, confound correction, and analysis once across the dataset,
including the configured group ICA, instead of repeating the full pipeline
separately for each subject. Results and workflow markers remain under
`<results directory>/cohort/`, allowing a rerun of the script to skip completed
stages and resume incomplete ones. Before the first stage, the job copies the
selected BIDS tree once to `<results directory>/cohort/input_bids/`, preserving
each `sub-*/ses-*` layout. RABIES then runs against that archived BIDS tree, so
the exact inputs are retained with the cohort outputs and are not recopied per
subject.

Use **Clear ALL results** to remove every item inside the results directory,
including the shared cohort outputs and cleaned timeseries. Cohort stages share
intermediate data across subjects, so **Clear selected results** is blocked
for a cohort run. Use **Clear ALL results** instead. The action requires
confirmation and leaves the results directory itself in place.

The output cleanup controls remove legacy per-subject workflow folders created
by earlier GUI versions. They preserve generated scripts and shared files and
do not remove current cohort results from `rabies_results`.

Choose **RABIES arguments…** to edit the command-line options for each of the
three stages. The editors start with the options used by the original batch
script; changes are applied to scripts created while the GUI is open. Enter
arguments in RABIES CLI form without the stage name or input/output paths.
Braced dictionary values are supported, for example
`--scan_QC_thresholds '{DR:{Dice:[0.3]}}'`.

**Remove cohort script** deletes `scrip_cohort.sh` from `tmp_script/`; it does
not delete processing outputs. Use **Create cohort script** to generate it
again with the current arguments.

Select subjects and choose **Move cleaned timeseries** to move their
`*_cleaned.nii.gz` files from the cohort confound-correction datasink into the
shared `<results>/cleaned_timeseries/` folder. This action moves files (it does
not copy them), keeps their filenames, and skips files when a destination with
the same name already exists.

The cohort job expects `*_bold.nii.gz` and `*_T2w.nii.gz` files in BIDS
structure and RABIES 0.6.3. The default stage arguments use the SIGMA rat template
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