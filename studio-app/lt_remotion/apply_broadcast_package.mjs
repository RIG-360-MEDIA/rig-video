#!/usr/bin/env node
// Final-stage broadcast graphics module for the H3 main pipeline.
//
// Usage:
//   node apply_broadcast_package.mjs <input_video.mp4> <story.json> <output_video.mp4>
//
// story.json supplies ONLY the per-video content (anchor name/title,
// headline, ticker items, optional timing overrides) — nothing about a
// specific video's technical specs (duration/fps/resolution) needs to be in
// it; those are auto-detected from the input video via ffprobe and merged in
// at render time, so the same story.json content shape works for any video.

import { execFile } from "child_process";
import { promisify } from "util";
import { readFile, writeFile, mkdtemp, rm } from "fs/promises";
import { tmpdir } from "os";
import path from "path";
import { fileURLToPath } from "url";

const execFileP = promisify(execFile);
const __dirname = path.dirname(fileURLToPath(import.meta.url));

async function ffprobe(videoPath) {
  const { stdout } = await execFileP("ffprobe", [
    "-v", "error",
    "-select_streams", "v:0",
    "-show_entries", "stream=width,height,avg_frame_rate",
    "-show_entries", "format=duration",
    "-of", "json",
    videoPath,
  ]);
  const info = JSON.parse(stdout);
  const stream = info.streams[0];
  const [num, den] = stream.avg_frame_rate.split("/").map(Number);
  const fps = den ? Math.round(num / den) : Math.round(num);
  return {
    width: stream.width,
    height: stream.height,
    fps,
    durationSeconds: parseFloat(info.format.duration),
  };
}

async function main() {
  const [, , videoPath, storyPath, outputPath] = process.argv;
  if (!videoPath || !storyPath || !outputPath) {
    console.error("Usage: node apply_broadcast_package.mjs <input_video.mp4> <story.json> <output_video.mp4>");
    process.exit(1);
  }

  console.log(`[1/4] Probing ${videoPath} ...`);
  const video = await ffprobe(videoPath);
  console.log(`      ${video.width}x${video.height} @ ${video.fps}fps, ${video.durationSeconds.toFixed(2)}s`);

  const storyRaw = JSON.parse(await readFile(storyPath, "utf-8"));

  // Inline a logo PNG so Remotion can render it without asset plumbing.
  // story.logo may be a path (resolved relative to the story file, then CWD)
  // or an object { src, heightPx?, startSeconds? }. A path/src that is already
  // a data:/http(s): URL is passed through untouched.
  const inlineLogo = async (val) => {
    if (!val || val.startsWith("data:") || val.startsWith("http")) return val;
    const candidates = [path.resolve(path.dirname(storyPath), val), path.resolve(process.cwd(), val), val];
    for (const p of candidates) {
      try {
        const buf = await readFile(p);
        const ext = path.extname(p).slice(1).toLowerCase() || "png";
        console.log(`      logo inlined from ${p}`);
        return `data:image/${ext === "jpg" ? "jpeg" : ext};base64,${buf.toString("base64")}`;
      } catch {}
    }
    console.warn(`      WARNING: logo not found: ${val} (skipping logo)`);
    return "";
  };
  if (storyRaw.logo) {
    if (typeof storyRaw.logo === "string") storyRaw.logo = await inlineLogo(storyRaw.logo);
    else storyRaw.logo = { ...storyRaw.logo, src: await inlineLogo(storyRaw.logo.src) };
  }

  const story = { ...storyRaw, video };

  const tmpDir = await mkdtemp(path.join(tmpdir(), "bcast-"));
  const propsPath = path.join(tmpDir, "props.json");
  await writeFile(propsPath, JSON.stringify({ story }, null, 2));

  const overlayPath = path.join(tmpDir, "overlay.mov");
  console.log(`[2/4] Rendering broadcast package overlay (alpha) ...`);
  await execFileP(
    "npx",
    [
      "remotion", "render",
      path.join(__dirname, "src/index.jsx"), "BroadcastPackage", overlayPath,
      "--props", propsPath,
      "--codec=prores", "--prores-profile=4444",
      "--image-format=png", "--pixel-format=yuva444p10le", ...(process.env.LT_CONCURRENCY ? [`--concurrency=${process.env.LT_CONCURRENCY}`] : []),
    ],
    { cwd: __dirname, maxBuffer: 1024 * 1024 * 64 }
  );
  console.log(`      overlay rendered -> ${overlayPath}`);

  console.log(`[3/4] Compositing overlay onto ${videoPath} ...`);
  await execFileP("ffmpeg", [
    "-v", "error",
    "-i", videoPath,
    "-i", overlayPath,
    "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[vout]",
    "-map", "[vout]", "-map", "0:a",
    "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "copy",
    "-y", outputPath,
  ]);
  console.log(`      composited -> ${outputPath}`);

  // Optional outro: concat a bumper (e.g. DNL Outro.mp4) onto the end,
  // normalized to this video's resolution/fps. story.outro = path (resolved
  // relative to the story file, then CWD).
  if (storyRaw.outro) {
    const cands = [path.resolve(path.dirname(storyPath), storyRaw.outro), path.resolve(process.cwd(), storyRaw.outro), storyRaw.outro];
    let outroPath = "";
    for (const p of cands) { try { await readFile(p); outroPath = p; break; } catch {} }
    if (!outroPath) {
      console.warn(`      WARNING: outro not found: ${storyRaw.outro} (skipping)`);
    } else {
      console.log(`[+] Appending outro ${outroPath} ...`);
      const withOutro = path.join(tmpDir, "final_outro.mp4");
      const { width: W, height: H, fps } = video;
      await execFileP("ffmpeg", [
        "-v", "error", "-i", outputPath, "-i", outroPath,
        "-filter_complex",
        `[1:v]scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=${fps}[o];` +
        `[0:v][0:a][o][1:a]concat=n=2:v=1:a=1[vout][aout]`,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-y", withOutro,
      ]);
      await execFileP("ffmpeg", ["-v", "error", "-i", withOutro, "-c", "copy", "-y", outputPath]);
      console.log(`      outro appended -> ${outputPath}`);
    }
  }

  console.log(`[4/4] Cleaning up ...`);
  await rm(tmpDir, { recursive: true, force: true });

  console.log("DONE");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
