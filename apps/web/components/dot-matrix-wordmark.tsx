"use client";

import { useEffect, useRef } from "react";

import { simplexNoise } from "@/components/dot-matrix/energy-field";
import {
  createDotCloud,
  type DotCloud,
} from "@/components/dot-matrix/glyph-mask";

const LABEL = "MemoryOS";
const IDLE = "rgba(163, 149, 242, .08)";
const PRIMARY = "#a395f2";
const SECONDARY = "#7465d5";
// Keep the reference field cadence: a broad simplex field blended with a
// stable per-cell hash produces the long, coherent sweeps through the glyph.
const ACTIVE_THRESHOLD = 0.24;
const NOISE_SCALE = 0.002;
const NOISE_BLEND = 0.7;
const TRAVEL_SPEED = 0.5;

function drawFrame(
  context: CanvasRenderingContext2D,
  cloud: DotCloud,
  elapsed: number,
) {
  context.clearRect(0, 0, cloud.width, cloud.height);
  context.fillStyle = IDLE;
  for (let index = 0; index < cloud.count; index += 1) {
    context.fillRect(
      cloud.positions[index * 2],
      cloud.positions[index * 2 + 1],
      cloud.size,
      cloud.size,
    );
  }

  let activeColor = "";
  const travel = elapsed * TRAVEL_SPEED;
  for (let index = 0; index < cloud.count; index += 1) {
    const noise = simplexNoise(
      cloud.cells[index * 2] * NOISE_SCALE + travel,
      cloud.cells[index * 2 + 1] * NOISE_SCALE + travel,
    );
    const threshold =
      cloud.staticNoise[index] * (1 - NOISE_BLEND) + noise * NOISE_BLEND;
    if (threshold >= ACTIVE_THRESHOLD) continue;
    const nextColor = cloud.colorNoise[index] < 0.34 ? SECONDARY : PRIMARY;
    if (nextColor !== activeColor) {
      context.fillStyle = nextColor;
      activeColor = nextColor;
    }
    context.fillRect(
      cloud.positions[index * 2],
      cloud.positions[index * 2 + 1],
      cloud.size,
      cloud.size,
    );
  }
}

export function DotMatrixWordmark() {
  const sectionRef = useRef<HTMLElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    const canvas = canvasRef.current;
    if (!section || !canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let cloud: DotCloud | null = null;
    let animationFrame = 0;
    let resizeTimer = 0;
    let visible = false;
    let disposed = false;
    let startedAt = performance.now() / 1000;

    const render = (timestamp: number) => {
      if (!cloud) return;
      drawFrame(context, cloud, timestamp / 1000 - startedAt);
      if (visible && !reducedMotion.matches) {
        animationFrame = requestAnimationFrame(render);
      } else {
        animationFrame = 0;
      }
    };

    const rebuild = () => {
      const bounds = section.getBoundingClientRect();
      // Match the reference cloud's minimum raster size. The CSS stage can be
      // smaller on mobile, but the mask still samples the same coordinate field.
      const width = Math.max(320, bounds.width);
      const height = Math.max(360, bounds.height);
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      cloud = createDotCloud(width, height, LABEL);
      canvas.dataset.dotCount = String(cloud.count);
      canvas.dataset.gridStep = cloud.step.toFixed(2);
      canvas.dataset.cellSize = cloud.size.toFixed(2);
      canvas.dataset.dpr = dpr.toFixed(2);
      drawFrame(
        context,
        cloud,
        reducedMotion.matches ? 8.25 : performance.now() / 1000 - startedAt,
      );
      if (visible && !reducedMotion.matches && !animationFrame) start();
      else
        canvas.dataset.animation = reducedMotion.matches
          ? "reduced"
          : visible
            ? "running"
            : "ready";
    };

    const start = () => {
      if (reducedMotion.matches || animationFrame || !cloud) {
        if (reducedMotion.matches) canvas.dataset.animation = "reduced";
        return;
      }
      startedAt = performance.now() / 1000;
      canvas.dataset.animation = "running";
      animationFrame = requestAnimationFrame(render);
    };

    const stop = () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      canvas.dataset.animation = "paused";
    };

    const intersectionObserver = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting;
        if (entry.isIntersecting) start();
        else stop();
      },
      { rootMargin: "200px" },
    );
    intersectionObserver.observe(section);

    const resizeObserver = new ResizeObserver(() => {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(rebuild, 120);
    });
    resizeObserver.observe(section);

    const onMotionChange = () => {
      stop();
      rebuild();
      if (visible) start();
    };
    reducedMotion.addEventListener("change", onMotionChange);
    void document.fonts.ready.then(() => {
      if (!disposed) rebuild();
    });
    rebuild();

    return () => {
      disposed = true;
      stop();
      intersectionObserver.disconnect();
      resizeObserver.disconnect();
      reducedMotion.removeEventListener("change", onMotionChange);
      window.clearTimeout(resizeTimer);
    };
  }, []);

  return (
    <section
      ref={sectionRef}
      className="dot-wordmark-section"
      aria-label="MemoryOS pixel wordmark"
    >
      <canvas
        ref={canvasRef}
        className="dot-wordmark-canvas"
        role="img"
        aria-label="MemoryOS rendered from illuminated square cells"
      />
    </section>
  );
}
