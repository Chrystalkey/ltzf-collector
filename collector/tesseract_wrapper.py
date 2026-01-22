import os
import re
import subprocess
import logging

from PIL import Image
from pathlib import Path

logger = logging.getLogger("collector")


def check_availability() -> bool:
    # check if tesseract with -l deu works
    with subprocess.Popen(
        ["tesseract", "--version"], stdout=subprocess.PIPE, encoding="utf-8"
    ) as proc:
        outs, errs = proc.communicate(timeout=5)
        lines = outs.split("\n")
        parts = lines[0].split(" ")
        if parts[0] != "tesseract":
            logger.critical("Expected to find Tesseract")
            return False
        version_parts = parts[1].split(".")
        if version_parts[0] != "5":
            logger.critical(f"Expected Tesseract version 5, got: {lines[0]}")
            return False

    with subprocess.Popen(
        ["tesseract", "--list-langs"], stdout=subprocess.PIPE, encoding="utf-8"
    ) as proc:
        outs, errs = proc.communicate(timeout=5)
        lines = outs.split("\n")
        if "deu" not in lines:
            logger.critical("Expected to find german language for tesseract")
            return False

    # check if pdfimages works
    with subprocess.Popen(
        ["pdfimages", "--version"], stderr=subprocess.PIPE, encoding="utf-8"
    ) as proc:
        o, e = proc.communicate(timeout=5)
        lines = e.split("\n")
        vnum = lines[0].split(" ")[2]
        v_maj = int(vnum.split(".")[0])

        if v_maj < 20:
            logger.critical(
                f"Expected to find pdfimages version 20 or higher in line {lines[0]}"
            )
            return False
    return True


def extract_ocr_text(pdf_path: Path) -> str:
    img_p = sanitize_images(pdf_to_img(pdf_path))
    txts = filter_useful_str(img_to_txt(img_p))
    return "".join(txts)


# run pdfimages -png pdf_path /tmp/images/img_base_path
def pdf_to_img(pdf_path: Path) -> list[Path]:
    parent = Path(f"/tmp/ltzf-cache/{pdf_path.name}.d")
    parent.absolute().mkdir(parents=True, exist_ok=True)

    command = ["pdfimages", "-png", pdf_path.absolute(), str(parent / "img")]
    logger.debug(f"Running {command}")
    p = subprocess.run(command)
    if p.returncode != 0:
        logger.error("Error: Extracting images failed")
        return None
    # filter images based on a oom-scheme
    # the largest image and everything above max / 10
    max_sz = 0
    files = []
    for f in parent.iterdir():
        if f.is_file() and f.suffix == ".png":
            max_sz = max(max_sz, f.stat().st_size)
            files.append(f)
    return [f for f in files if f.stat().st_size >= max_sz / 10]


# run tesseract command with the image it is given.
# does not do any changes to the image and has one special case:
# that is when tesseract does not get enough characters
def determine_rotation(image: Path) -> int:
    rot_deg = None
    with subprocess.Popen(
        ["tesseract", "--psm", "0", imgp.absolute(), "-"],
        stdout=subprocess.PIPE,
        encoding="utf-8",
    ) as p:
        o, e = p.communicate(timeout=5)
        lines = o.split("\n")
        for l in lines:
            if l.startswith("Rotate: "):
                rot_deg = int(l.split(" ")[1])
                break
        if rot_deg is None and "Too few characters." not in o:
            logger.error(
                f"Unable to determine page direction due to unknown Tesseract output:\n{o}"
            )
            return None
    return rot_deg


def sanitize_images(images: list[Path]) -> list[Path]:
    #    for imgp in images:
    #        # let tesseract guess the best rotation
    #        determine_rotation(imgp)
    #        # then rotate according to that
    #        img = Image.open(imgp.absolute())
    #        img.rotate(360 - rot_deg).save(imgp.absolute())
    return images


def img_to_txt(images: list[Path]) -> list[str]:
    # run tesseract -l deu images[i] images[i].txt
    strings = []
    for img in sorted(images):
        p = subprocess.run(["tesseract", "-l", "deu", "--psm", "1", img, img])
        if p.returncode != 0:
            logger.error("Error extracting {img}")
            return None
        with open(str(img) + ".txt", "r", encoding="utf-8") as file:
            strings.append(file.read())
    return strings


min_sane = re.compile(r"\w\w\w+")


def filter_useful_str(strings: list[str]) -> list[str]:
    # filter out strings that do not even resemble words
    global min_sane
    return [s for s in strings if min_sane.match(s)]


if __name__ == "__main__":
    print(check_availability())
    #    print(extract_ocr_text(Path("/home/crystalkey/Downloads/0000000041.pdf")))
    print(extract_ocr_text(Path("/home/crystalkey/Downloads/0000000003.pdf")))
