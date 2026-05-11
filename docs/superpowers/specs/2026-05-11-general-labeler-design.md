# General Data Labeler Design

## Goal

Make the existing image labeling page usable for different labeling tasks without changing the script for each task.

## Scope

The page keeps the existing src/ref/tgt/json loading flow, image display, pass/fail labeling, reasoning fields, pagination, and export folder layout. This change only makes label dimensions configurable and lets the user choose the exported JSON filename.

## Label Dimensions

`groundtruth` is always included and cannot be removed. The page provides an empty "extra dimensions" input. Users may enter additional dimensions separated by commas, Chinese commas, semicolons, spaces, or new lines. Blank values are ignored. Duplicate dimensions are removed while preserving the first occurrence. If users type `groundtruth`, it is not duplicated.

Each active dimension has:

- a pass/fail/clear judgment
- a `<dimension>_reasoning` field

The backend stores the active dimensions in the Flask process state for the currently loaded dataset. All validation, statistics, empty label records, and export records read from that state.

## Export Filename

The export panel includes an export JSON filename input. If left blank, the filename defaults to `labeled_export.json`. The backend strips directory components, replaces filesystem-invalid filename characters with `_`, and appends `.json` when the user omits it.

## Out Of Scope

This change does not add persistent saved sessions, change the image folder layout, change prompt parsing, or alter the source/ref/target matching rule.
