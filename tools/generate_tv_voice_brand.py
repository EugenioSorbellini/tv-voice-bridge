"""Render the TV/microphone mark from simple geometric primitives."""

from pathlib import Path

from PIL import Image, ImageDraw


def main() -> None:
    destination = Path(__file__).resolve().parents[1] / "custom_components/tv_voice_bridge/brand"
    destination.mkdir(parents=True, exist_ok=True)
    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        scale = size / 256
        image = Image.new("RGBA", (size, size))
        draw = ImageDraw.Draw(image)

        def box(values, scale=scale):
            return tuple(round(value * scale) for value in values)

        draw.rounded_rectangle(box((12, 22, 244, 202)), radius=round(28 * scale), fill="#132b3c")
        draw.rounded_rectangle(
            box((28, 38, 228, 186)),
            radius=round(16 * scale),
            outline="#35c4ef",
            width=round(8 * scale),
        )
        draw.rounded_rectangle(box((107, 57, 149, 126)), radius=round(21 * scale), fill="#ffffff")
        draw.arc(box((86, 77, 170, 151)), 0, 180, fill="#35c4ef", width=round(8 * scale))
        draw.line(box((128, 151, 128, 168)), fill="#35c4ef", width=round(8 * scale))
        draw.line(box((108, 168, 148, 168)), fill="#35c4ef", width=round(8 * scale))
        draw.line(box((96, 220, 160, 220)), fill="#132b3c", width=round(12 * scale))
        draw.line(box((128, 202, 128, 220)), fill="#132b3c", width=round(12 * scale))
        image.save(destination / name)


if __name__ == "__main__":
    main()
