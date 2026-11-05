# RABIES subject and cohort manager

The unified PySide6 GUI provides subject/session and cohort-wide workflows for
viewing BIDS subjects, checking NIfTI orientations, and creating or submitting
RABIES/FIXRABIES SLURM jobs:

- `rabies_gui_core.py` opens the unified GUI. Choose single-subject/session
  jobs or cohort-wide jobs from the **Analysis mode** dropdown.
- `rabies_subject_manager.py` remains a compatibility entry point for the
  standalone subject/session GUI, creating one independent job per BIDS session
  for selected subjects. It supports preprocessing-only,
  preprocessing-plus-confound, full-pipeline, and preprocessing-plus-FIXRABIES
  prepare variants for each session, plus a FIXRABIES-prepare-only variant for
  subjects whose preprocessing outputs already exist.
- `rabies_cohort_manager.py` is also available as an entry point for the
  unified GUI, including one cohort-wide job for the full selected BIDS
  dataset using RABIES' native subject/session handling.

Run the GUI in a Linux desktop or X11-forwarded session that can access the
BIDS, output, and results directories. To submit jobs from the GUI, that
system must also have `sbatch` available. For example:

```sh
python -m pip install -r rabies_gui_requirements.txt
# Unified GUI with the analysis-mode dropdown
python rabies_gui_core.py
# One job per BIDS session for selected subjects
python rabies_subject_manager.py
# Unified GUI, also available through this entry point
python rabies_cohort_manager.py
```

Both managers use the same project setup and stage arguments. Their generated
scripts, workflow outputs, and archived stage results use separate paths;
both modes use the shared `cleaned_timeseries` folder when files are moved
there.

FIXRABIES scripts call the `fixrabies` command directly, so FIXRABIES and its
required FSL/FIX dependencies must be available in the job's environment.
Choose the FIX species/template space from the dropdown beside the pipeline
selector: `ratSIGMA`, `mouseDSURQE`, or `mouseAIBS`. See the upstream
[FIXRABIES installation instructions](https://github.com/grandjeanlab/FixRABIES#installation).
The selected FIXRABIES species must match the common-space template used for
RABIES preprocessing; adjust the RABIES arguments when using a non-rat space.

The GUI opens in the **RABIES Project Setup** window. Browse to the project
root, output directory, results directory, RABIES image, and template folder
(rat, mouse, or custom). Choosing a project root fills the output and results
paths with `<project root>/rabies_outputs/` and
`<project root>/rabies_results/`; edit those fields afterward if needed.
Existing output folders and generated scripts are not moved automatically;
regenerate scripts to use the new `rabies_outputs/single-subject` and
`rabies_outputs/cohort` working directories.
When launched from a terminal, the current working directory is used as the
initial project root. If it contains a `bids/` folder with subject directories
matching the selected subject prefix, that folder is selected as the original
BIDS folder automatically.
Both managers display `RABIES-RABIES.png` as a splash image while they start.
Keep the image beside the Python scripts; if it is missing or cannot be loaded,
the GUI starts normally without a splash.

The cohort manager's **Analysis mode** dropdown switches between
**Single-subject/session scripts and batch jobs** and **Cohort script and batch
job**. Only the controls for the selected mode are shown. The first mode
creates a separate `scrip_<subject>_<session>.sh` for each selected session,
using the pipeline selected next to **Create script**. The cohort mode exposes
the cohort pipeline, FIX species, and cohort script controls. Subject browsing
and shared input tools remain available in either mode.
Scripts are saved under
`<output>/tmp_script/{preproc_only,preproc_confound,whole_pipeline,fixrabies_prepare,fixrabies_prepare_only}/`.
Standard pipeline scripts stage only that session's BOLD/T2w files and write
stage outputs under
`<output>/single-subject/func_<stage>/<subject>/<session>/` and archived
results under
`<results>/<subject>/<session>/`. The FIXRABIES-prepare-only variant skips BIDS
staging and uses the existing preprocessing outputs. For FIXRABIES, choose
**Create new shared FIX
folder…** or an existing FIX folder from the **FIX folder** selector. When
creating a folder, enter a custom folder name in **New folder name** (or leave
it blank for an automatically generated name); new folders are created directly
under the project root. All selected subject/session scripts then use that same
folder and selected species. Existing FIX folders reject a species mismatch.
The subject table shows each subject's assigned FIX folder(s), including
assignments for scripts that have not yet run. Prepared scan data is stored
under `<project root>/<FIX folder>/data/`. The generated jobs serialize FIX
preparation with a shared lock, so they can be submitted together without
running their FIX workflows concurrently against the same directory.
Both GUIs provide a checked-by-default **Delete RABIES working outputs after
archiving to rabies_results** option. For per-session jobs, it removes the
session's staged BIDS input and preprocessing, confound, and analysis folders
from `<output>/single-subject/` after archiving. For cohort jobs, it removes
the working stage and FIXRABIES folders from `<output>/cohort/` after
archiving. Archived results in `rabies_results` are never removed by this
option. Uncheck it when creating scripts to retain working outputs; remove
per-session output with **Clear selected output** or **Clear ALL subject
output**, and cohort output with **Clear cohort output**.
Choose **FIXRABIES prepare only** to create jobs that run only `fixrabies
prepare` against existing per-session preprocessing outputs. The GUI checks
that each selected subject/session has a preprocessing workflow before creating
these scripts. These jobs request 4 GB of memory and 4 CPUs; the combined
preprocessing-plus-FIX variant retains its 8 GB request. Choose **Submit
scripts with sbatch** and select which pipeline
variant to submit. With no session rows selected, it
submits eligible sessions for the selected subjects and skips sessions that
already have results for that pipeline's stages. If session rows are selected,
it submits only those sessions for the current subject. To rerun completed
stages, choose **Clear selected session results** first. Each session's
analysis is independent; it does not combine data across sessions or subjects
for group ICA.

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

The subject/session manager contains the subject table, per-session stage
status, script controls, cleanup actions, and cleaned-timeseries tools. It
shows BOLD and T2w scan counts and the status of preprocessing, confound
correction, analysis, and FIXRABIES preparation. In cohort mode, a separate
status line reports cohort-wide stage completion.
Select a subject to view its sessions, every RABIES-relevant NIfTI's
orientation, the input source, and the applicable session or cohort stage
results. Data under a session's `mrs/` directory is ignored by scan counts and
orientation checks/reorientation. RABIES' default BIDS filters select
functional `bold`/`cbv` and anatomical `T1w`/`T2w` suffixes, so MRS files are
not selected. Script
creation is allowed regardless of orientation, but job submission is blocked
if any BIDS NIfTI is unreadable or is not in RAS orientation. Orientation
entries show a concise session/modality label; hover over an entry to see its
full path. Use **Reorient selected NIfTIs to RAS** to convert non-RAS files.
The GUI asks for confirmation, preserves originals in a timestamped
`<BIDS folder>_orientation_backups` directory beside the BIDS folder, and
replaces the input files with RAS-oriented copies. If a cohort input snapshot
already exists from an older GUI script, new cohort jobs read the selected
original BIDS folder instead; the old snapshot is not used.

RABIES stage status is based on the corresponding
`rabies_<stage>_workflow.pkl` file. FIXRABIES status is based on prepared scan
directories in the selected project's shared FIX folder for per-session jobs.
The subject table also lists shared FIX folders assigned to each subject. The
cohort manager's cohort-mode status line reports completion from
`<results directory>/cohort/`, including FIXRABIES scan data under
`<results directory>/cohort/fixrabies/data/`.

In **Single-subject/session** mode, use the pipeline dropdown next to **Create
script** for per-session jobs. In **Cohort** mode, choose a pipeline from the
**Cohort pipeline** dropdown and select **Create cohort script**. Cohort
scripts are saved under
`<output directory>/tmp_script/{preproc_only,preproc_confound,whole_pipeline,fixrabies_prepare}/`.
Choose **Submit cohort with sbatch** to submit the selected cohort-wide
variant as one job for every subject and session in the selected BIDS folder.
Selection in the subject table is only for viewing subject details and
reorienting selected files; it does not narrow the analysis cohort. Each
script runs preprocessing only, preprocessing followed by confound correction,
the whole RABIES pipeline (including analysis), or preprocessing followed by
`fixrabies prepare`. For FIXRABIES, the selected species/template space is
passed to the prepare command, which converts the RABIES preprocessing outputs
into FIX-compatible scan directories under
`<output directory>/cohort/fixrabies/data/`, then runs MELODIC and extracts
FIX features. Each script passes the selected original BIDS directory to
RABIES as a read-only input. RABIES discovers and pairs subject/session scans
using its native BIDS handling; it does not need a copied BIDS snapshot.
RABIES runs the selected preprocessing and analysis stages once across the
dataset, including the configured group ICA for the full pipeline, instead of
repeating them separately for each subject. Results and workflow markers
remain under `<results directory>/cohort/`, allowing a rerun of the script to
skip completed stages and resume incomplete ones. Working stage outputs are
under `<output directory>/cohort/`; the delete-after-archive option removes
these working copies only after they have been copied to the results
directory. The selected BIDS directory must be separate from both output and
results directories.

The `.input_bids.*` temporary directories were created by the older custom
snapshot step in generated cohort scripts. New scripts do not create them.
Regenerate previously created cohort scripts before submitting another job;
do not remove a staging directory while an older job may still be running.

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

In **Cohort** mode, **Remove cohort scripts** deletes generated scripts from the
pipeline subfolders of `tmp_script/`; it does not delete processing outputs.
Select a variant and use **Create cohort script** to generate it again with the
current arguments.

Select subjects and choose **Move cleaned timeseries** to move their
`*_cleaned.nii.gz` files from the cohort confound-correction datasink into the
shared `<results>/cleaned_timeseries/` folder. This action moves files (it does
not copy them), keeps their filenames, and skips files when a destination with
the same name already exists.

The cohort job expects `*_bold.nii.gz` and `*_T2w.nii.gz` files in BIDS
structure and RABIES 0.6.3. The default stage arguments use the SIGMA rat template
layout. When selecting mouse or custom templates, use **RABIES arguments…** in
the manager to set the corresponding template and atlas file paths, and
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