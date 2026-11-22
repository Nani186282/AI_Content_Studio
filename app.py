import io
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import imageio_ffmpeg
import requests
import streamlit as st
from google import genai
from PIL import Image, ImageDraw, ImageFont, ImageOps

st.set_page_config(page_title="AI Content Studio", page_icon="🎨")
st.title("🎨 AI Content Studio")

secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

try:
    with secrets_path.open("rb") as file:
        config = tomllib.load(file)
except (OSError, ValueError) as error:
    st.error(f"Cannot read configuration: {secrets_path}")
    st.error(str(error))
    st.stop()

for key in ["GEMINI_API_KEY", "STABILITY_API_KEY"]:
    if not isinstance(config.get(key), str) or not config[key].strip():
        st.error(f"Missing or empty top-level entry: {key}")
        st.info(f"Edit the file: {secrets_path}")
        st.stop()

idea = st.text_input("Enter Your Idea", "app demonstration", max_chars=100)
audience = st.text_input("Audience", "business clients", max_chars=100)
cta = st.text_input(
    "Call to Action", "Join us and be a part of our app", max_chars=100
)
brief = f"Idea: {idea}. Audience: {audience}. Call to action: {cta}."

if st.session_state.get("brief") != brief:
    st.session_state.brief = brief
    st.session_state.content = None
    st.session_state.poster = None
    st.session_state.video = None

if not all(value.strip() for value in [idea, audience, cta]):
    st.info("Fill all three fields.")
    st.stop()

# 1. Text generation
if st.button("1. Generate captions and script"):
    try:
        with st.spinner("Gemini is writing..."):
            client = genai.Client(api_key=config["GEMINI_API_KEY"].strip())
            result = client.interactions.create(
                model=config.get("TEXT_MODEL", "gemini-3.5-flash-lite"),
                input=(
                    f"{brief} Write Instagram and WhatsApp captions and a "
                    "15-second promotional script. Use only supplied facts. "
                    "Do not invent dates, prices, or links."
                ),
            )
            if not result.output_text:
                raise ValueError("Gemini returned no text.")
            st.session_state.content = result.output_text
    except Exception as e:
        st.error(f"Writing failed: {e}")

if st.session_state.get("content"):
    st.write(st.session_state.content)
    st.download_button(
        "Download writing",
        st.session_state.content,
        file_name="Campaign.txt",
        mime="text/plain",
    )

# 2. Poster generation
if st.button("2. Generate Stable Diffusion poster"):
    try:
        with st.spinner("Stability AI is generating artwork..."):
            prompt = (
                f"A cinematic promotional illustration for {idea} aimed at "
                f"{audience}. A confident presenter on a modern stage in front "
                "of a glowing digital dashboard screen with an engaged business "
                "audience. Deep navy blue and golden yellow lighting, sleek "
                "3D corporate illustration, clean composition, no text, no "
                "logos, no watermarks."
            )
            response = requests.post(
                "https://api.stability.ai/v2beta/stable-image/generate/sd3",
                headers={
                    "Authorization": f"Bearer {config['STABILITY_API_KEY'].strip()}",
                    "Accept": "image/*",
                },
                files={"none": ""},
                data={
                    "prompt": prompt,
                    "model": "sd3.5-large-turbo",
                    "aspect_ratio": "2:3",
                    "output_format": "png",
                },
                timeout=(10, 90),
            )
            response.raise_for_status()
            art = Image.open(io.BytesIO(response.content)).convert("RGB")

            poster = Image.new("RGB", (432, 768), "#071D3F")
            poster.paste(ImageOps.fit(art, (432, 560)), (0, 0))

            try:
                title_font = ImageFont.load_default(size=26)
                body_font = ImageFont.load_default(size=20)
            except TypeError:
                title_font = ImageFont.load_default()
                body_font = ImageFont.load_default()

            draw = ImageDraw.Draw(poster)
            draw.multiline_text(
                (20, 580),
                textwrap.fill(idea, 25),
                font=title_font,
                fill="#FFD447",
            )
            draw.multiline_text(
                (20, 690),
                textwrap.fill(cta, 32),
                font=body_font,
                fill="white",
            )
            output = io.BytesIO()
            poster.save(output, format="PNG")
            st.session_state.update(poster=output.getvalue(), video=None)

    except requests.Timeout:
        st.error("Stability AI timed out. Check your account before retrying.")
    except requests.HTTPError as error:
        st.error(f"Stability API returned HTTP {error.response.status_code}")
        st.code(error.response.text[:1000], language="text")
    except Exception as error:
        st.error(f"Poster failed: {error}")

if st.session_state.get("poster"):
    st.image(st.session_state.poster, width=320)
    st.download_button(
        "Download poster",
        st.session_state.poster,
        file_name="poster.png",
        mime="image/png",
    )

# 3. Video export
if st.button("3. Export 15-second promo video"):
    if not st.session_state.get("poster"):
        st.warning("Generate a poster in Step 2 before exporting the video.")
    else:
        try:
            with st.spinner("Exporting video..."):
                with tempfile.TemporaryDirectory() as folder:
                    source = Path(folder) / "poster.png"
                    target = Path(folder) / "promo.mp4"
                    source.write_bytes(st.session_state.poster)

                    subprocess.run(
                        [
                            imageio_ffmpeg.get_ffmpeg_exe(),
                            "-y",
                            "-loop",
                            "1",
                            "-framerate",
                            "6",
                            "-i",
                            str(source),
                            "-t",
                            "15",
                            "-vf",
                            "fade=t=in:st=0:d=0.5,fade=t=out:st=14.5:d=0.5,format=yuv420p",
                            "-c:v",
                            "libx264",
                            "-preset",
                            "ultrafast",
                            "-movflags",
                            "+faststart",
                            str(target),
                        ],
                        check=True,
                        capture_output=True,
                        timeout=30,
                    )
                    st.session_state.video = target.read_bytes()
        except subprocess.CalledProcessError as error:
            st.error("FFmpeg export failed.")
            st.code(error.stderr.decode(errors="replace")[-1000:])
        except Exception as error:
            st.error(f"Video export failed: {error}")

if st.session_state.get("video"):
    st.video(st.session_state.video)
    st.download_button(
        "Download video",
        st.session_state.video,
        file_name="promo.mp4",
        mime="video/mp4",
    )