import os
import time
import threading
import zipfile
import io
import streamlit as st
import state
from scrape_engine import run_scraper

st.set_page_config(
    page_title="Web Image Scraper",
    page_icon="🖼️",
    layout="wide"
)

st.markdown("""
<style>
    .main-title { font-size: 2.5rem; font-weight: 700; color: #1f77b4; }
    .sub-title  { font-size: 1rem; color: #888; margin-bottom: 2rem; }
    .stat-box   { background: #f0f4ff; border-radius: 10px; padding: 1rem;
                  text-align: center; border: 1px solid #d0e0ff; }
    .stat-num   { font-size: 2rem; font-weight: 700; color: #1f77b4; }
    .stat-label { font-size: 0.85rem; color: #555; }
</style>
""", unsafe_allow_html=True)

s = state.shared   # shorthand — same object every rerun

# ── Header ────────────────────────────────────────────────────
st.markdown('<div class="main-title">🖼️ Web Image Scraper</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Scrape and download images from any website — across multiple pages</div>', unsafe_allow_html=True)
st.divider()

left, right = st.columns([1, 2], gap="large")

# ── Settings panel ────────────────────────────────────────────
with left:
    st.subheader("⚙️ Settings")

    url = st.text_input(
        "Website URL",
        placeholder="https://www.example.com/products",
        disabled=s['running'],
    )
    max_pages = st.slider(
        "Number of pages to scrape",
        min_value=1, max_value=30, value=3,
        disabled=s['running'],
    )
    output_dir = st.text_input(
        "Save folder name",
        value="downloaded_images",
        disabled=s['running'],
    )
    headless = st.toggle(
        "Run browser in background",
        value=False,
        disabled=s['running'],
    )

    st.markdown("**Minimum image size** (skip smaller images)")
    col_w, col_h = st.columns(2)
    min_width = col_w.number_input(
        "Min width (px)", min_value=0, value=100, step=10,
        disabled=s['running'],
    )
    min_height = col_h.number_input(
        "Min height (px)", min_value=0, value=100, step=10,
        disabled=s['running'],
    )

    st.divider()

    if not s['running']:
        if st.button("🚀 Start Scraping", use_container_width=True, type="primary"):
            if not url.strip():
                st.error("Please enter a URL.")
            else:
                s['logs']       = ["Setting up browser..."]
                s['saved']      = []
                s['running']    = True
                s['done']       = False
                s['stop_event'] = threading.Event()

                def scrape_thread():
                    try:
                        saved = run_scraper(
                            url=url.strip(),
                            max_pages=max_pages,
                            output_dir=output_dir,
                            headless=headless,
                            log=lambda m: s['logs'].append(m),
                            stop_event=s['stop_event'],
                            min_width=int(min_width),
                            min_height=int(min_height),
                        )
                        s['saved'] = saved or []
                    except Exception as e:
                        s['logs'].append(f"Error: {e}")
                    finally:
                        s['running'] = False
                        s['done']    = True

                threading.Thread(target=scrape_thread, daemon=True).start()
                st.rerun()

    else:
        if st.button("⛔ Stop Scraping", use_container_width=True, type="secondary"):
            s['stop_event'].set()
            s['logs'].append("Stop requested — finishing current page...")

        if st.button("🔁 Force Reset", use_container_width=True):
            if s['stop_event']:
                s['stop_event'].set()
            s['running'] = False
            s['done']    = False
            s['logs']    = []
            s['saved']   = []
            st.rerun()

# ── Results panel ─────────────────────────────────────────────
with right:
    st.subheader("📊 Live Output")

    if not s['running'] and not s['done']:
        st.info("Configure settings on the left and click **Start Scraping**.")

    if s['running'] or s['done']:
        logs = s['logs']

        pages = sum(1 for l in logs if l.startswith("Scraping page"))
        total = 0
        for l in logs:
            if "total:" in l:
                try:
                    total = int(l.split("total:")[1].replace(")", "").strip())
                except Exception:
                    pass

        c1, c2, c3 = st.columns(3)
        for col, num, label in [
            (c1, pages,          "Pages crawled"),
            (c2, total,          "Images found"),
            (c3, len(s['saved']), "Images saved"),
        ]:
            col.markdown(f"""
            <div class="stat-box">
                <div class="stat-num">{num}</div>
                <div class="stat-label">{label}</div>
            </div>
            """, unsafe_allow_html=True)

        st.divider()
        st.code("\n".join(logs[-30:]) if logs else "Starting...", language=None)

        if s['running']:
            time.sleep(1)
            st.rerun()

        if s['done']:
            saved_count = len(s['saved'])
            if any("Stopped by user" in l for l in logs):
                st.warning(f"Stopped early. {saved_count} images saved to `{output_dir}/`")
            else:
                st.success(f"✅ Done! **{saved_count}** images saved to `{output_dir}/`")

            preview = [
                f for f in s['saved']
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif'))
            ][:12]

            if preview:
                st.subheader("🖼️ Preview (first 12 images)")
                cols = st.columns(4)
                for i, path in enumerate(preview):
                    try:
                        cols[i % 4].image(path, use_container_width=True)
                    except Exception:
                        pass

            st.caption(f"Saved at: `{os.path.abspath(output_dir)}`")

            # ZIP download
            if s['saved']:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for path in s['saved']:
                        if os.path.exists(path):
                            zf.write(path, os.path.basename(path))
                zip_buffer.seek(0)
                st.download_button(
                    label=f"⬇️ Download all {saved_count} images as ZIP",
                    data=zip_buffer,
                    file_name="scraped_images.zip",
                    mime="application/zip",
                    use_container_width=True,
                )

            if st.button("🔄 Scrape Again"):
                s['done']  = False
                s['logs']  = []
                s['saved'] = []
                st.rerun()
