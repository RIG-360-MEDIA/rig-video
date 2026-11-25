#!/usr/bin/env node
// Burns social-style captions onto a video via Remotion (rendered as a real
// alpha-channel overlay, then composited with ffmpeg's `overlay` filter --
// NOT ffmpeg's `subtitles`/`drawtext` filters, which require libass/
// libfreetype that this machine's ffmpeg build does not have compiled in).
//
// Usage:
//   node apply_captions.mjs <input_video.mp4> <cues.json> <output_video.mp4>
//
// cues.json shape: [{ "start": 0.0, "end": 0.73, "text": "GOOD EVENING." }, ...]
// (seconds, relative to the start of the video)

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
  const [, , videoPath, cuesPath, outputPath] = process.argv;
  if (!videoPath || !cuesPath || !outputPath) {
    console.error("Usage: node apply_captions.mjs <input_video.mp4> <cues.json> <output_video.mp4>");
    process.exit(1);
  }

  console.log(`[1/4] Probing ${videoPath} ...`);
  const video = await ffprobe(videoPath);
  console.log(`      ${video.width}x${video.height} @ ${video.fps}fps, ${video.durationSeconds.toFixed(2)}s`);

  const cues = JSON.parse(await readFile(cuesPath, "utf-8"));

  const tmpDir = await mkdtemp(path.join(tmpdir(), "captions-"));
  const propsPath = path.join(tmpDir, "props.json");
  await writeFile(propsPath, JSON.stringify({ cues, video }, null, 2));

  const overlayPath = path.join(tmpDir, "overlay.mov");
  console.log(`[2/4] Rendering captions overlay (alpha) ...`);
  await execFileP(
    "npx",
    [
      "remotion", "render",
      path.join(__dirname, "src/index.jsx"), "Captions", overlayPath,
      "--props", propsPath,
      "--codec=prores", "--prores-profile=4444",
      "--image-format=png", "--pixel-format=yuva444p10le",
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

  console.log(`[4/4] Cleaning up ...`);
  await rm(tmpDir, { recursive: true, force: true });

  console.log("DONE");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
