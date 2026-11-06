# RABIES analysis manager

The PySide6 GUI browses BIDS subjects and sessions, checks NIfTI orientations,
and creates or submits RABIES/FIXRABIES SLURM jobs. `rabies_gui_core.py` is the
supported entry point. The legacy `rabies_subject_manager.py` and
`rabies_cohort_manager.py` launchers are deprecated and will not be supported
in future versions.

## Install V1.6

Clone the V1.6 release, install its dependencies, and launch the unified GUI:

```sh
git clone --branch v1.6 https://github.com/WesselvEng/rabiesGUI.git
cd rabiesGUI
python -m pip install -r rabies_gui_requirements.txt
python rabies_gui_core.py
```

For an existing checkout:

```sh
git fetch --tags
git switch --detach v1.6
python -m pip install -r rabies_gui_requirements.txt
python rabies_gui_core.py
```

Run in a Linux desktop or X11-forwarded session with access to the project
files. Launch it from a terminal with `python rabies_gui_core.py` to see GUI
activity, generated job scripts, `sbatch` commands, and submission output.
SLURM submission also requires `sbatch`.

## Configure and choose a workflow

In Project Setup, select the project root, original BIDS folder, RABIES
Apptainer image, template folder, output directory, and results directory.
Choosing a project root defaults the latter paths to `rabies_outputs/` and
`rabies_results/`. The subject prefix defaults to `sub-`. The GUI may discover
a BIDS folder automatically when launched from a project containing `bids/`.

In the analysis manager, choose **Single-subject/session** to create independent
jobs for selected subject sessions, or **Cohort** for one job across the BIDS
dataset. Each mode offers a workflow-mode dropdown and large pipeline buttons:

- **Normal mode:** preprocessing only, preprocessing + confound correction,
  analysis only, or the full pipeline.
- **FIX mode:** preprocessing + FIXRABIES prepare, or FIXRABIES prepare only.
  Choose the matching FIX species/template space. Single-subject FIX jobs also
  use the selected shared FIX folder.

Analysis-only reads archived confound-correction outputs and requires the
`cleaned_timeseries` folder to remain in place. Do not move or remove it before
running analysis-only. FIX prepare-only requires existing preprocessing output.
FIXRABIES and its FSL/FIX dependencies must be available to the job; see the
[FIXRABIES installation instructions](https://github.com/grandjeanlab/FixRABIES#installation).

## Outputs and job controls

Scripts are created under
`<output>/tmp_script/<pipeline>/`. Per-session working data is under
`<output>/single-subject/`. When archiving is enabled, single-subject results
mirror that layout under `<results>/single-subject/` (for example,
`func_preprocess/<subject>/<session>/`). Cohort working data and archived
results are under `<output>/cohort/` and `<results>/cohort/`.
For cohort preprocessing, only
`preprocess/preprocess_QC_report/` is archived; the remaining preprocessing
working output is kept under `<output>/cohort/preprocess/` for analysis-only and
FIX prepare-only workflows. Cohort confound archiving includes only
`confound/confound_correction_datasink/cleaned_timeseries/`; analysis-only uses
those cleaned files from the archive. Cohort analysis archiving includes only
`analysis/commonspace_analysis_datasink/` and
`analysis/data_diagnosis_datasink/`. Other completed cohort working stages are
removed after archiving.

**Submit scripts with sbatch** submits the currently selected pipeline. With no
session rows selected, eligible sessions for the selected subjects are
submitted and sessions with existing results are skipped. Select session rows
to submit only those sessions. Clear results before rerunning completed stages.
Cohort jobs always process the full selected BIDS dataset; table selection is
for viewing, not filtering the cohort.

Job submission requires all relevant BIDS NIfTIs to be readable and in RAS
orientation. Use **Reorient selected NIfTIs to RAS** to convert files; originals
are backed up beside the BIDS folder. Files under `mrs/` are excluded from
orientation checks and scan counts.

The checked-by-default **Archiving** option copies stage results to the results
directory and then removes working outputs. When unchecked, jobs do not archive
any outputs and retain their working files.
Use **Archive existing output** to copy existing working outputs for selected
subjects (or the full cohort) into the results directory without deleting the
working copies. For cohorts, this archives only
`preprocess/preprocess_QC_report/` from preprocessing and
`confound/confound_correction_datasink/cleaned_timeseries/` from confound
correction, plus `analysis/commonspace_analysis_datasink/` and
`analysis/data_diagnosis_datasink/` from analysis. Progress is shown in the GUI
status and launch terminal. For SLURM jobs, archive-copy progress is written
to the job's standard output/error log. Existing archived files with matching
names may be replaced.
**Clear ALL results** removes archived results after confirmation. The
**Move cleaned timeseries** action moves `*_cleaned.nii.gz` files to
`<results>/cleaned_timeseries/`; analysis-only reads the prior confound outputs
from the working folders when archiving is off, or from the archive when on.
Identical source duplicates are removed after the move so only one copy remains
in the results tree; same-name files with different contents are reported as
conflicts and left untouched.

Use **RABIES arguments…** to edit stage CLI arguments before creating scripts.
For cohort workflows, preprocessing and analysis run across the dataset once.
They use the configured template paths and group analysis options.

## Templates

The selected template folder is bind-mounted as `/templates` in Apptainer.
Default arguments expect the following SIGMA rat layout:

```text
templates/
├── anatomy/
│   ├── SIGMA_InVivo_Brain_Template.nii.gz
│   ├── SIGMA_InVivo_Brain_Mask.nii.gz
│   ├── SIGMA_InVivo_WM_bin.nii.gz
│   └── SIGMA_InVivo_CSF_bin.nii.gz
├── atlas/
│   └── SIGMA_Anatomical_Brain_Atlas.nii.gz
└── canica_resting_state.nii.gz
```

For mouse or custom templates, update the preprocessing arguments
(`--anat_template`, `--brain_mask`, `--WM_mask`, `--CSF_mask`,
`--vascular_mask`) and analysis arguments (`--ROI_labels_file`, `--prior_maps`)
to use paths under `/templates`. Review generated scripts before submission.
