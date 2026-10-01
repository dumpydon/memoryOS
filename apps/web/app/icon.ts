import { memoryMark } from "@/lib/brand";

export const contentType = "image/svg+xml";
export const size = { width: 32, height: 32 };

export default function Icon() {
  return new Response(
    `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="${memoryMark.viewBox}">
      <style>
        .trace { fill: #7263d7; }
        .return { fill: #1f2937; }
        @media (prefers-color-scheme: dark) {
          .trace { fill: #a395f2; }
          .return { fill: #e7ebf2; }
        }
      </style>
      <path class="trace" d="${memoryMark.paths[0]}" />
      <path class="return" d="${memoryMark.paths[1]}" />
    </svg>`,
    { headers: { "Content-Type": contentType } },
  );
}
