import sheet from "../assets/quack-spritesheet.png";

const FRAME_SIZE = 36;
const FRAME_COUNT = 3;
const FRAME_MS = 100;
const SCALE = 1;

export default function QuackSprite() {
  const size = FRAME_SIZE * SCALE;

  return (
    <span
      aria-hidden="true"
      className="quack-sprite inline-block shrink-0 align-middle"
      style={{
        width: size,
        height: size,
        backgroundImage: `url(${sheet})`,
        backgroundSize: `${size * FRAME_COUNT}px ${size}px`,
        animation: `quack-sprite ${FRAME_MS * FRAME_COUNT}ms steps(${FRAME_COUNT}) infinite`,
        ["--sprite-end" as string]: `-${size * FRAME_COUNT}px`,
        imageRendering: "pixelated",
      }}
    />
  );
}
