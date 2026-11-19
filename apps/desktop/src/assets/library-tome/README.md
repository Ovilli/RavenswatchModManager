# Library Paladin Tome

`paladin-tome.glb` is the unchanged user-supplied **Paladin Tome** by
[Mike Chan (rikuchan)](https://sketchfab.com/rikuchan), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
[Original model](https://sketchfab.com/3d-models/paladin-tome-e8af23487fed49e9abf87b5a3c902a66).

`paladin-poster.webp` is a transparent render with the same camera, pose and
lighting, used during loading and when WebGL is unavailable or its context is
lost. Regenerate the poster when changing the pose or lighting in
`src/lib/library-tome.ts`.

The renderer is lazy-loaded, runs only on load, resize and context restoration,
and disposes GPU resources on unmount. Floating motion and the sparkles rising
from the book's crease use CSS and respect both the OS and in-app reduced-motion
preferences.
