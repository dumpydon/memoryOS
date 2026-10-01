// Two returning ribbons, offset by half a turn around a shared aperture.
// Shared by the sidebar SVG and the browser icon so their geometry stays identical.
export const memoryMark = {
  viewBox: "-2 -2 40 40",
  paths: [
    "M3.7 11.3 14.3 0.7Q15 0 15.7 0.7L29.3 14.3Q30 15 29.3 15.7L24 21 15 12 9 18 3.7 12.7Q3 12 3.7 11.3Z",
    "M32.3 24.7 21.7 35.3Q21 36 20.3 35.3L6.7 21.7Q6 21 6.7 20.3L12 15 21 24 27 18 32.3 23.3Q33 24 32.3 24.7Z",
  ],
} as const;
