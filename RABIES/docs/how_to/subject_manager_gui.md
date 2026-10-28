# Manage subjects with the GUI

`rabies_subject_manager.py` is a PySide6 application for viewing BIDS
subjects, checking completed RABIES stages, and creating or submitting one
SLURM job script per selected subject.

Run the GUI in a Linux desktop or X11-forwarded session that can access the
BIDS, output, and results directories. To submit jobs from the GUI, that
system must also have `sbatch` available. For example:

```sh
python -m pip install -r scripts/rabies_gui_requirements.txt
python scripts/rabies_subject_manager.py
```

Project root and original BIDS folder are intentionally not hard-coded. Use
**Browse…** beside Project root, then choose the BIDS folder from the
**Original BIDS folder (og_folder)** dropdown. The dropdown lists direct
subfolders of the project root that contain `sub-*` subject folders; the BIDS
folder does not have to be named `og_bids`. Choosing a project root fills the
output and results paths with `<project root>/rabies_output/` and
`<project root>/rabies_results/`; edit those fields afterward if needed.
Refresh the subject list after selecting the BIDS folder. The table shows BOLD
and T2w scan counts and the status of preprocessing, confound correction, and
analysis.

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

Each generated job expects the same per-subject inputs and options as the
example pipeline: `*_bold.nii.gz` and `*_T2w.nii.gz` files, the SIGMA rat
template layout, and RABIES 0.6.3. Review the generated scripts before
submission if your data layout or processing options differ.
