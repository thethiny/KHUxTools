# To check later

## Fusion cost and special attack (server guesses F1 / F2)

The server now copies the client's fusion preview (`SceneMixedMedal::updateMaterial`), but two details come from
reading the decompile, not from a test.

1. Fuse in game, then compare the Munny the preview shows with the server log line
   `MEDAL ENHANCE: +<exp> exp -> lv <n> exp <n>, special +<n>, cost <N>` (in `recomp/server_emu.log`).
   - Cost should be: number of medals fed x 80 x the base medal's level.
   - **Also fuse onto a max-level medal:** the cost should then be 25% of that (F1).
2. Fuse a copy of the same medal (or a medal of the same group) and check that the special attack goes up by the
   copy's special-attack level, as the preview shows (F2).

If either differs, tell Claude the preview numbers and the log line.
