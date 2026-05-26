# Images Per Row Design

## Goal

Add a page control that lets the user choose how many images appear per row inside each sample group. The control applies to all images in the group: `cond_1`, `cond_2`, and every target image.

## Behavior

- Add an `Images Per Row` numeric control in the toolbar.
- Valid range is `1` to `8`; default is `4`.
- Save the chosen value in browser `localStorage`.
- Changing the value updates the current page immediately without reloading the dataset.
- Each group renders one unified image grid in this order: `cond_1`, `cond_2`, target 1, target 2, and so on.
- Shared `cond_1` and `cond_2` image blocks do not have label buttons.
- Target image blocks keep `Pass`, `Fail`, and `Clear`.
- Existing keyboard labeling, selected target behavior, zoom/pan, and target-to-source press comparison remain unchanged.
- On narrow screens, CSS may collapse the grid to fewer columns to keep images usable.

## Implementation Notes

The frontend owns this feature. The backend response shape does not need to change. `static/app.js` should store `imagesPerRow` in state and set `--images-per-row` on group cards or grids. `static/style.css` should use that variable for the unified image grid. `index.html` should add the toolbar input.

## Verification

- Static regression tests should confirm the control exists, the localStorage key is wired, the unified image grid is rendered, and CSS uses the image-per-row variable.
- Manual browser verification should load a group with shared images and targets, switch the control between several values, and confirm all images in the group reflow together.
