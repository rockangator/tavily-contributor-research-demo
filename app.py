from __future__ import annotations

import base64
import html
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from dotenv import load_dotenv

from contributor_lens.export import sidecar_json
from contributor_lens.models import ContributorAssessment, RepoAssessment, RepoRef
from contributor_lens.pipeline import analyze_repository, load_fixture, save_assessment


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
LATEST_LIVE_REPORT = DATA / "latest_live_report.json"
REPOSITORY_PRESETS = {
    "Tavily Python": "https://github.com/tavily-ai/tavily-python",
    "PyMath": "https://github.com/RustPython/pymath",
    "SymPy": "https://github.com/sympy/sympy",
    "LangSmith SDK": "https://github.com/langchain-ai/langsmith-sdk",
}

CREAM = "#FEFCF5"
INK = "#3C3A39"
ORANGE = "#FF7300"
ACTION_BLUE = "#2677FF"

load_dotenv(ROOT / ".env")

st.set_page_config(
    page_title="Contributor Analysis · Tavily",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False)
def asset_data_uri(path: str, mime_type: str) -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def format_generated_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%b %d, %Y · %H:%M UTC")
    except (TypeError, ValueError):
        return value


def compact_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}m"
    if value >= 1_000:
        return f"{value / 1_000:.1f}k"
    return f"{value:,}"


def source_outcome(item: ContributorAssessment) -> tuple[str, str]:
    if item.error:
        return "Search incomplete", "status-partial"
    if not item.evidence:
        return "No retained matches", "status-limited"
    if any(source.identity_match == "exact" for source in item.evidence):
        return "Exact match found", "status-strong"
    return "Probable match only", "status-partial"


def source_outcome_explanation(
    item: ContributorAssessment,
    source_mode: str = "live",
) -> str:
    search_count = len(item.search_queries)
    login = item.profile.login
    if item.error:
        return (
            "The public-source search did not complete for this contributor. "
            "The GitHub facts are still available, but the Tavily portion should be retried."
        )
    if not item.evidence:
        if source_mode == "snapshot":
            return (
                f"This saved report contains no retained public source for @{login}. "
                "Run a live analysis to refresh the search. This is not a negative finding "
                "about the contributor."
            )
        return (
            f"Tavily ran {search_count} identity-focused search{'es' if search_count != 1 else ''}, "
            f"but the app retained no page for @{login}. Any returned pages lacked enough matching "
            "details to safely tie them to this GitHub account. "
            "This is not a negative finding about the contributor."
        )
    exact_count = sum(source.identity_match == "exact" for source in item.evidence)
    if source_mode == "snapshot":
        return (
            f"This saved report contains {len(item.evidence)} real public source"
            f"{'s' if len(item.evidence) != 1 else ''}. {exact_count} include the GitHub "
            "handle plus the contributor name or repository context."
        )
    if exact_count:
        return (
            f"{len(item.evidence)} source{'s were' if len(item.evidence) != 1 else ' was'} retained. "
            f"{exact_count} included the GitHub handle plus the contributor name or repository context."
        )
    return (
        f"{len(item.evidence)} source{'s were' if len(item.evidence) != 1 else ' was'} retained as a "
        "probable identity match. Confirm it manually before using it as evidence."
    )


def preferred_contributor(assessment: RepoAssessment) -> ContributorAssessment | None:
    if not assessment.contributors:
        return None
    return max(
        assessment.contributors,
        key=lambda item: (
            bool(item.evidence),
            sum(source.identity_match == "exact" for source in item.evidence),
            len(item.evidence),
            item.profile.contributions,
        ),
    )


def selection_key(assessment: RepoAssessment, surface: str) -> str:
    return (
        f"{surface}::{assessment.source_mode}::"
        f"{assessment.repository.full_name}::{assessment.generated_at}"
    )


def sync_contributor_selection(source_key: str, peer_key: str) -> None:
    login = st.session_state.get(source_key)
    if not login:
        return
    st.session_state.selected_login = login
    if peer_key in st.session_state:
        st.session_state[peer_key] = login


def selected_contributor(assessment: RepoAssessment) -> ContributorAssessment | None:
    if not assessment.contributors:
        return None
    valid_logins = {item.profile.login for item in assessment.contributors}
    login = st.session_state.get("selected_login")
    if login not in valid_logins:
        preferred = preferred_contributor(assessment)
        login = preferred.profile.login if preferred else None
        st.session_state.selected_login = login
    return next(item for item in assessment.contributors if item.profile.login == login)


def initialize_state() -> None:
    st.session_state.setdefault("repository_preset", next(iter(REPOSITORY_PRESETS)))
    if st.session_state.repository_preset not in REPOSITORY_PRESETS:
        st.session_state.repository_preset = next(iter(REPOSITORY_PRESETS))
    st.session_state.setdefault(
        "live_repository",
        REPOSITORY_PRESETS[st.session_state.repository_preset],
    )
    st.session_state.setdefault("tavily_key", os.getenv("TAVILY_API_KEY", ""))
    st.session_state.setdefault("github_token", os.getenv("GITHUB_TOKEN", ""))
    st.session_state.setdefault("project_id", os.getenv("TAVILY_PROJECT_ID", ""))
    st.session_state.setdefault("contributor_limit", 5)
    st.session_state.setdefault("deep_extract", False)

    if "live_assessment" not in st.session_state:
        try:
            st.session_state.live_assessment = (
                load_fixture(LATEST_LIVE_REPORT) if LATEST_LIVE_REPORT.exists() else None
            )
        except (OSError, ValueError, KeyError, TypeError):
            st.session_state.live_assessment = None
    st.session_state.setdefault("active_report_id", None)
    st.session_state.setdefault("selected_login", None)


INTER_FONT_URI = asset_data_uri(
    str(ASSETS / "fonts" / "Inter-Variable.ttf"),
    "font/ttf",
)


def inject_styles() -> None:
    st.markdown(
        f"""
        <style>
        @font-face {{
            font-family: "Inter";
            src: url("{INTER_FONT_URI}") format("truetype");
            font-style: normal;
            font-weight: 100 900;
            font-display: swap;
        }}
        :root {{
            --cream: {CREAM};
            --ink: {INK};
            --action: {ACTION_BLUE};
            --orange: {ORANGE};
            --orange-soft: #FFF1E5;
            --sky: #79DEEB;
            --sky-soft: #EAFBFD;
            --lavender: #F2A6FF;
            --lavender-soft: #FBEFFE;
            --mint: #9BE6C1;
            --mint-soft: #EAF8F1;
            --amber-soft: #FFF5DA;
            --muted: #69645E;
            --line: #DED8CF;
            --panel: rgba(255, 252, 246, .78);
        }}

        html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] * {{
            font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            color: var(--ink);
        }}
        code, pre, kbd, samp, [data-testid="stCode"] * {{
            font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace !important;
        }}
        [data-testid="stIconMaterial"], [data-testid="stIconMaterial"] *,
        .material-symbols-rounded, .material-symbols-outlined {{
            font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
            font-weight: normal !important;
            font-style: normal !important;
        }}
        [data-testid="stAppViewContainer"] {{
            background-color: var(--cream);
            background-image:
                radial-gradient(64rem 24rem at 14% -3%, rgba(121, 222, 235, .30), transparent 66%),
                radial-gradient(58rem 25rem at 84% 5%, rgba(242, 166, 255, .22), transparent 68%),
                radial-gradient(40rem 26rem at 54% 18%, rgba(255, 115, 0, .13), transparent 68%),
                linear-gradient(180deg, #F3FCFA 0%, #FEFCF5 22rem, #FEFCF5 100%);
            background-position: center top;
            background-size: cover;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        [data-testid="stHeader"] {{ background: transparent; height: 0; }}
        [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {{ display: none !important; }}
        [data-testid="stSidebar"] {{ display: none; }}
        .block-container {{ max-width: 1160px; padding: .9rem 2rem 2.75rem; }}

        h1, h2, h3, h4, p {{ color: var(--ink); }}
        h1 {{ font-size: 34px !important; line-height: 1.14 !important; font-weight: 620 !important; letter-spacing: -.035em !important; }}
        h2, h3, h4 {{ font-weight: 620 !important; letter-spacing: -.018em !important; }}
        p {{ line-height: 1.5; }}

        .brand-spectrum {{
            width: 100%; height: 3px; margin-bottom: 12px; border-radius: 99px;
            background: linear-gradient(90deg, var(--orange) 0 27%, var(--sky) 27% 52%, var(--lavender) 52% 76%, var(--mint) 76% 100%);
        }}
        .app-header {{ display: flex; align-items: center; min-height: 38px; }}
        .tavily-wordmark {{ display: inline-flex; align-items: center; font-size: 19px; font-weight: 720; letter-spacing: -.035em; }}
        .header-divider {{ width: 1px; height: 22px; margin: 0 13px; background: #CBC7BF; }}
        .header-title {{ font-size: 13px; font-weight: 620; }}
        .github-link {{
            box-sizing: border-box; width: auto; min-width: 64px; height: 34px; padding: 0 12px; margin: 0 0 0 auto; display: grid; place-items: center;
            color: var(--ink) !important; border: 1px solid rgba(60,58,57,.16); border-radius: 999px;
            background: rgba(255,252,246,.72); backdrop-filter: blur(15px); text-decoration: none !important;
            font-size: 11px; font-weight: 620;
            transition: transform .18s ease, box-shadow .18s ease;
        }}
        .github-link:hover {{ transform: translateY(-1px); box-shadow: 0 7px 16px rgba(60,58,57,.10); }}

        [class*="st-key-app_header"] [data-testid="stHorizontalBlock"] {{ align-items: center; gap: 12px; }}
        [class*="st-key-app_header"] [data-testid="stColumn"] {{ display: flex; align-items: center; min-height: 40px; }}
        [class*="st-key-app_header"] [data-testid="stColumn"] > div {{ width: 100%; }}
        [class*="st-key-app_header"] [data-testid="stColumn"]:has(.github-link) [data-testid="stElementContainer"],
        [class*="st-key-app_header"] [data-testid="stColumn"]:has([data-testid="stPopover"]) [data-testid="stElementContainer"] {{
            display: flex; align-items: center; min-height: 40px; margin: 0 !important;
        }}
        [class*="st-key-app_header"] [data-testid="stColumn"]:has(.github-link) [data-testid="stMarkdownContainer"] {{
            display: flex; align-items: center; justify-content: flex-end; width: 100%; min-height: 40px;
        }}
        [class*="st-key-app_header"] [data-testid="stColumn"]:has(.github-link) p {{
            display: flex; align-items: center; justify-content: flex-end; margin: 0;
        }}
        [class*="st-key-app_header"] [data-testid="stPopover"] {{
            position: relative; top: 7px; display: flex; align-items: center; min-height: 40px;
        }}
        [class*="st-key-app_header"] [data-testid="stPopover"] > button {{ min-height: 38px; height: 38px; margin: 0; }}

        .page-intro {{ padding: 1.25rem 0 .35rem; }}
        .page-intro h1 {{ margin: 0 0 .5rem; }}
        .page-intro p {{ margin: 0; color: var(--muted); font-size: 14px; max-width: 720px; }}
        [class*="st-key-repository_picker"] [data-testid="stVerticalBlock"] {{ gap: .35rem; }}
        [class*="st-key-repository_picker"] {{ margin-top: .05rem; margin-bottom: .25rem; }}

        .data-notice {{ margin: 8px 0 11px; padding: 8px 12px; border: 1px solid rgba(60,58,57,.13); border-left: 3px solid var(--action); border-radius: 10px; background: rgba(255,252,246,.72); backdrop-filter: blur(15px); font-size: 12px; color: #55514C; }}
        .data-notice strong {{ color: var(--ink); }}

        .panel {{ background: var(--panel); border: 1px solid rgba(255,255,255,.82); border-radius: 12px; box-shadow: 0 8px 26px rgba(60,58,57,.055); backdrop-filter: blur(15px); }}
        .field-label {{ display: block; margin-bottom: 3px; font-size: 11px; color: var(--muted); }}
        .field-value {{ font-size: 15px; font-weight: 650; }}

        .repo-panel {{ margin: 0 0 14px; padding: 15px 18px 0; overflow: hidden; }}
        .repo-top {{ display: grid; grid-template-columns: minmax(260px, 1fr) minmax(520px, 1.08fr); gap: 24px; align-items: start; }}
        .repo-kicker {{ margin-bottom: 5px; color: var(--muted); font-size: 10px; font-weight: 720; letter-spacing: .08em; text-transform: uppercase; }}
        .repo-name {{ font-size: 18px; font-weight: 680; letter-spacing: -.018em; }}
        .repo-description {{ margin-top: 5px; color: var(--muted); font-size: 12px; line-height: 1.5; }}
        .repo-facts {{ display: grid; grid-template-columns: 1fr .9fr 1.18fr 1.08fr; }}
        .repo-fact {{ min-width: 0; padding: 2px 12px 0; border-left: 1px solid var(--line); }}
        .repo-fact-value {{ font-size: 16px; font-weight: 670; }}
        .repo-fact-label {{ margin-top: 3px; color: var(--muted); font-size: 9.5px; line-height: 1.25; }}
        .pipeline {{ display: flex; align-items: center; margin: 14px -18px 0; padding: 8px 18px; border-top: 1px solid rgba(60,58,57,.10); background: rgba(255,252,246,.54); color: #4E4A45; font-size: 11px; }}
        .pipeline-context {{ margin-right: 14px; color: var(--muted); font-size: 9px; font-weight: 720; letter-spacing: .07em; text-transform: uppercase; }}
        .pipeline-step {{ display: inline-flex; align-items: center; gap: 7px; }}
        .pipeline-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}
        .pipeline-arrow {{ margin: 0 12px; color: #AAA39A; }}

        [data-testid="stTabs"] {{ margin-top: 2px; }}
        [data-testid="stTab"] {{ padding: 0 13px !important; }}
        [data-testid="stTab"] p {{ font-size: 13px; font-weight: 580; }}
        [data-testid="stTab"][aria-selected="true"] p {{ color: var(--ink) !important; font-weight: 680; }}
        [data-testid="stTab"] .react-aria-SelectionIndicator {{ background: var(--orange) !important; height: 2px !important; }}
        [data-testid="stTabContent"] {{ padding-top: 1rem; }}

        .tab-heading {{ margin-bottom: 10px; }}
        .tab-heading h2 {{ margin: 0 0 5px; font-size: 21px; }}
        .tab-heading p {{ margin: 0; color: var(--muted); font-size: 12px; }}

        .status-strip {{ display: grid; grid-template-columns: repeat(3, 1fr); overflow: hidden; margin-bottom: 10px; }}
        .status-cell {{ padding: 17px 18px 15px; }}
        .status-cell + .status-cell {{ border-left: 1px solid var(--line); }}
        .status-marker {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 7px; }}
        .status-strong .status-marker {{ background: #62C99A; }}
        .status-partial .status-marker {{ background: var(--orange); }}
        .status-limited .status-marker {{ background: #CC75DC; }}
        .status-count {{ display: block; margin-top: 5px; font-size: 24px; font-weight: 650; letter-spacing: -.03em; }}
        .status-name {{ font-size: 11px; font-weight: 620; }}
        .status-caption {{ margin: 0 0 22px; color: var(--muted); font-size: 11px; }}
        .preview-label {{ margin: 20px 0 9px; font-size: 12px; font-weight: 680; }}

        .workspace-label {{ margin-bottom: 4px; color: var(--muted); font-size: 10px; font-weight: 720; letter-spacing: .08em; text-transform: uppercase; }}
        .workspace-title {{ margin: 0 0 3px; font-size: 16px; font-weight: 660; }}
        .workspace-caption {{ margin-bottom: 12px; color: var(--muted); font-size: 11px; }}
        .profile-heading {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 13px; }}
        .profile-heading h2 {{ margin: 0; font-size: 23px; }}
        .profile-handle {{ margin-top: 3px; color: var(--muted); font-size: 12px; }}
        .status-badge {{ padding: 5px 8px; border-radius: 99px; font-size: 10px; font-weight: 700; white-space: nowrap; }}
        .status-badge.status-strong {{ background: var(--mint-soft); color: #276C50; border: 1px solid #BDE8D2; }}
        .status-badge.status-partial {{ background: var(--amber-soft); color: #80520D; border: 1px solid #EEDBA0; }}
        .status-badge.status-limited {{ background: var(--lavender-soft); color: #764683; border: 1px solid #E8C3EF; }}

        .person-panel {{ padding: 19px 20px; }}
        .person-facts {{ display: grid; grid-template-columns: repeat(4, 1fr); border-bottom: 1px solid var(--line); }}
        .person-fact {{ padding: 14px 0; }}
        .person-fact + .person-fact {{ border-left: 1px solid var(--line); padding-left: 16px; }}
        .detail-grid {{ display: grid; grid-template-columns: 1.1fr .9fr; gap: 30px; padding-top: 17px; }}
        .detail-title {{ margin-bottom: 8px; font-size: 12px; font-weight: 700; }}
        .detail-list {{ margin: 0; padding-left: 18px; }}
        .detail-list li {{ margin: 6px 0; font-size: 12px; color: #4F4B46; }}
        .profile-row {{ display: flex; justify-content: space-between; gap: 16px; padding: 7px 0; border-bottom: 1px solid #EFEEE9; font-size: 12px; }}
        .profile-row span:first-child {{ color: var(--muted); }}
        .profile-row span:last-child {{ max-width: 67%; text-align: right; font-weight: 550; }}
        .outcome-note {{ margin: 15px 0 0; padding: 10px 12px; border: 1px solid #BDE7EC; border-radius: 7px; background: var(--sky-soft); color: #315C61; font-size: 11px; line-height: 1.5; }}
        .outcome-note strong {{ color: var(--ink); }}
        .searches-run {{ margin-top: 14px; }}
        .searches-run h4 {{ margin: 0 0 7px; font-size: 11px; }}

        [class*="st-key-contributor_choice"] div[role="radiogroup"] {{ gap: 7px; }}
        [class*="st-key-contributor_choice"] .stRadio label {{ margin: 0; padding: 10px 11px; border: 1px solid var(--line); border-radius: 7px; background: #FFF; }}
        [class*="st-key-contributor_choice"] .stRadio label:hover {{ border-color: #BDB5AA; }}
        [class*="st-key-contributor_choice"] .stRadio label:has(input:checked) {{ border-color: var(--orange); background: #FFF8F1; }}
        [class*="st-key-contributor_choice"] .stRadio label p {{ font-size: 11px; line-height: 1.35; }}

        .sample-note {{ margin-bottom: 10px; padding: 9px 11px; border-radius: 6px; background: #FFF3E8; color: #74400F; font-size: 11px; }}
        .tavily-source-label {{ display: inline-flex; align-items: center; gap: 7px; margin-bottom: 10px; padding: 5px 8px; border: 1px solid #BDE7EC; border-radius: 99px; background: var(--sky-soft); color: #245F66; font-size: 10px; font-weight: 680; }}
        .tavily-source-label::before {{ content: ""; display: block; width: 7px; height: 7px; border-radius: 50%; background: var(--sky); }}
        .source-list {{ padding: 0 18px; }}
        .source-row {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; column-gap: 18px; padding: 17px 0; border-bottom: 1px solid var(--line); }}
        .source-row:last-child {{ border-bottom: 0; }}
        .source-title {{ font-size: 14px; font-weight: 650; }}
        .source-title a {{ color: var(--ink); text-decoration: underline; text-decoration-color: var(--orange); text-underline-offset: 3px; }}
        .source-meta {{ margin-top: 3px; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }}
        .source-excerpt {{ margin-top: 7px; max-width: 760px; font-size: 12px; line-height: 1.5; color: #55514C; }}
        .match-label {{ align-self: start; padding: 4px 7px; border: 1px solid var(--line); border-radius: 99px; background: #FBFAF7; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; }}
        .match-exact {{ border-color: #BDE8D2; background: var(--mint-soft); color: #276C50; }}
        .match-probable {{ border-color: #E8C3EF; background: var(--lavender-soft); color: #764683; }}

        .empty-state {{ padding: 28px 22px; text-align: center; }}
        .empty-state h3 {{ margin: 0 0 6px; font-size: 18px; }}
        .empty-state p {{ margin: 0 auto; max-width: 560px; color: var(--muted); font-size: 12px; }}

        .export-panel {{ padding: 19px 20px; max-width: 760px; }}
        .export-panel h3 {{ margin: 0 0 5px; font-size: 17px; }}
        .export-panel p {{ margin: 0 0 16px; font-size: 12px; color: var(--muted); }}
        .export-scope {{ display: grid; grid-template-columns: 1fr 1fr; margin: 16px 0 0; border-top: 1px solid var(--line); }}
        .scope-column {{ padding: 15px 18px 5px 0; }}
        .scope-column + .scope-column {{ padding-left: 18px; border-left: 1px solid var(--line); }}
        .scope-column h4 {{ margin: 0 0 7px; font-size: 11px; }}
        .scope-column ul {{ margin: 0; padding-left: 16px; }}
        .scope-column li {{ margin: 4px 0; color: var(--muted); font-size: 11px; }}

        @keyframes button-shine {{ from {{ transform: translateX(-180%) skewX(-18deg); }} to {{ transform: translateX(430%) skewX(-18deg); }} }}
        .stButton > button, .stDownloadButton > button {{ border-radius: 999px !important; min-height: 40px; font-size: 12px; font-weight: 650; transition: transform .18s ease, box-shadow .18s ease; }}
        .stButton > button[kind="primary"] {{ position: relative; overflow: hidden; background: #1F1E1E !important; border-color: #1F1E1E !important; color: #FEFCF5 !important; box-shadow: 0 7px 16px rgba(31,30,30,.14); }}
        .stButton > button[kind="primary"] p {{ color: #FEFCF5 !important; }}
        .stButton > button[kind="primary"]::after {{ content: ""; position: absolute; inset: -20% auto -20% -30%; width: 22%; background: linear-gradient(90deg, transparent, rgba(255,255,255,.34), transparent); animation: button-shine 1.1s ease 1; }}
        .stButton > button[kind="primary"]:hover {{ transform: scale(1.055); box-shadow: 0 10px 22px rgba(31,30,30,.18); }}
        .stDownloadButton > button {{
            background: rgba(255,252,246,.88) !important; border: 1px solid rgba(60,58,57,.20) !important;
            color: var(--ink) !important; box-shadow: none !important;
        }}
        .stDownloadButton > button p {{ color: var(--ink) !important; }}
        .stDownloadButton > button:hover {{ background: #FFFCF6 !important; border-color: rgba(60,58,57,.34) !important; transform: none; }}
        [data-testid="stPopover"] button {{ border-color: rgba(60,58,57,.15); border-radius: 999px; background: rgba(255,252,246,.76); backdrop-filter: blur(15px); }}
        [data-baseweb="popover"] {{ max-width: 390px; }}
        [data-baseweb="popover"] > div {{ background: rgba(255,252,246,.96) !important; border: 1px solid rgba(60,58,57,.13); box-shadow: 0 10px 28px rgba(31,30,30,.10) !important; backdrop-filter: blur(18px); }}
        [data-testid="stTextInput"] input {{ background: rgba(255,252,246,.82); border-radius: 10px; }}
        [data-testid="stExpander"] {{ border-color: rgba(60,58,57,.12); border-radius: 10px; background: rgba(255,252,246,.72); backdrop-filter: blur(15px); }}
        [class*="st-key-source_details_shell"] {{ margin-top: -.25rem; }}
        [class*="st-key-source_details_shell"] [data-testid="stVerticalBlock"] {{ gap: .55rem; }}
        [class*="st-key-source_details_shell"] [data-testid="stExpander"] {{
            border-color: rgba(60,58,57,.11); border-radius: 9px; background: rgba(255,252,246,.62);
            box-shadow: none;
        }}
        [class*="st-key-source_details_shell"] [data-testid="stExpander"] summary {{
            min-height: 42px; padding: 0 14px !important;
        }}
        [class*="st-key-source_details_shell"] [data-testid="stExpander"] summary p {{
            font-size: 12px; font-weight: 500; color: #55514C;
        }}
        [data-testid="stDataFrame"] {{ border: 1px solid var(--line); border-radius: 7px; overflow: hidden; }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{ border-color: rgba(60,58,57,.12); border-radius: 12px; background: rgba(255,252,246,.76); backdrop-filter: blur(15px); }}
        [data-testid="stSegmentedControl"] label {{ border-radius: 999px !important; }}
        [data-testid="stSegmentedControl"] p {{ font-size: 12px; }}
        button:focus-visible, a:focus-visible, input:focus-visible {{ outline: 2px solid var(--action) !important; outline-offset: 2px; }}

        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{ animation-duration: .01ms !important; animation-iteration-count: 1 !important; transition-duration: .01ms !important; }}
        }}

        @media (max-width: 820px) {{
            .block-container {{ padding-left: 1rem; padding-right: 1rem; }}
            .repo-top {{ grid-template-columns: 1fr; }}
            .repo-facts {{ grid-template-columns: repeat(2, 1fr); row-gap: 14px; }}
            .person-facts {{ grid-template-columns: 1fr 1fr; }}
            .person-fact + .person-fact {{ border-left: 0; padding-left: 0; }}
            .detail-grid {{ grid-template-columns: 1fr; }}
            .status-strip {{ grid-template-columns: 1fr; }}
            .status-cell + .status-cell {{ border-left: 0; border-top: 1px solid var(--line); }}
            .export-scope {{ grid-template-columns: 1fr; }}
            .scope-column + .scope-column {{ padding-left: 0; border-left: 0; border-top: 1px solid var(--line); }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def active_repository_url() -> str:
    assessment = st.session_state.get("live_assessment")
    if assessment is not None:
        return assessment.repository.html_url
    try:
        return RepoRef.parse(st.session_state.get("live_repository", "")).url
    except ValueError:
        return "https://github.com/tavily-ai/tavily-python"


def render_header_and_settings() -> str:
    st.markdown('<div class="brand-spectrum"></div>', unsafe_allow_html=True)
    with st.container(key="app_header"):
        left, github, settings = st.columns([7.3, 1.15, 1.55], vertical_alignment="center")
        with left:
            st.markdown(
                f"""
                <div class="app-header">
                    <span class="tavily-wordmark">Tavily</span>
                    <span class="header-divider"></span>
                    <span class="header-title">Contributor research</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with settings:
            with st.popover("Settings"):
                with st.expander("Connections", expanded=True):
                    st.text_input(
                        "Tavily API key",
                        key="tavily_key",
                        type="password",
                        placeholder="Required for live analysis",
                    )
                    st.text_input(
                        "GitHub token (optional)",
                        key="github_token",
                        type="password",
                        placeholder="Increases the GitHub API limit",
                    )
                with st.expander("Advanced"):
                    st.text_input(
                        "Tavily project ID (optional)",
                        key="project_id",
                        type="password",
                    )
                with st.expander("Analysis options"):
                    st.slider("Number of contributors", 3, 12, key="contributor_limit")
                    st.checkbox(
                        "Extract content from matched pages",
                        key="deep_extract",
                        help="Uses Tavily Extract on the strongest matched results.",
                    )
                st.caption("Keys stay in this session and are never included in exports.")
        with github:
            repository_url = active_repository_url()
            st.markdown(
                f"""
                <a class="github-link" href="{esc(repository_url)}" target="_blank" rel="noopener noreferrer" aria-label="Open repository on GitHub" title="Open repository on GitHub">GitHub</a>
                """,
                unsafe_allow_html=True,
            )
    return "Live repository"


def select_repository_preset() -> None:
    st.session_state.live_repository = REPOSITORY_PRESETS[
        st.session_state.repository_preset
    ]


def render_repository_controls(mode: str) -> bool:
    st.markdown(
        """
        <div class="page-intro">
            <h1>Open-source contributor research</h1>
            <p>Review repository activity, contributor profiles, and identity-matched public sources.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="repository_picker"):
        st.markdown(
            '<div class="workspace-label">Suggested repositories</div>',
            unsafe_allow_html=True,
        )
        st.segmented_control(
            "Suggested repositories",
            options=list(REPOSITORY_PRESETS),
            key="repository_preset",
            label_visibility="collapsed",
            on_change=select_repository_preset,
        )

    field, action = st.columns([5.7, 1.3], vertical_alignment="bottom")
    with field:
        st.text_input(
            "GitHub repository",
            key="live_repository",
            help="Use a public github.com repository URL or owner/repository.",
        )
    with action:
        return st.button(
            "Run analysis",
            type="primary",
            width="stretch",
            key="analyze_repository",
        )


def run_live_analysis() -> None:
    api_key = st.session_state.tavily_key.strip()
    if not api_key:
        st.error("Add a Tavily API key in Settings.")
        return
    try:
        repo = RepoRef.parse(st.session_state.live_repository)
    except ValueError as exc:
        st.error(str(exc))
        return

    try:
        with st.spinner("Analyzing repository…"):
            result = analyze_repository(
                repo=repo,
                top_n=int(st.session_state.contributor_limit),
                github_token=st.session_state.github_token.strip() or None,
                tavily_api_key=api_key,
                tavily_project_id=st.session_state.project_id.strip() or None,
                deep_extract=bool(st.session_state.deep_extract),
            )
    except Exception as exc:
        st.error(f"Analysis failed: {exc}")
        return

    st.session_state.live_assessment = result
    try:
        save_assessment(result, LATEST_LIVE_REPORT)
    except OSError as exc:
        st.warning(f"The report is available now, but it could not be saved locally: {exc}")
    st.session_state.active_report_id = None
    preferred = preferred_contributor(result)
    st.session_state.selected_login = preferred.profile.login if preferred else None
    st.rerun()


def sync_assessment(mode: str) -> RepoAssessment | None:
    assessment = st.session_state.get("live_assessment")
    if assessment is None:
        return None
    report_id = f"live::{assessment.repository.full_name}::{assessment.generated_at}"

    if st.session_state.get("active_report_id") != report_id:
        preferred = preferred_contributor(assessment)
        st.session_state.selected_login = preferred.profile.login if preferred else None
        st.session_state.active_report_id = report_id
    return assessment


def render_data_notice(assessment: RepoAssessment | None, mode: str) -> None:
    if assessment is None:
        text = (
            "<strong>No live report yet.</strong> Add a Tavily API key in Settings, then run an "
            "analysis. The completed report will remain available when you switch views or restart the app."
        )
    elif assessment.source_mode == "snapshot":
        source_count = sum(len(item.evidence) for item in assessment.contributors)
        text = (
            "<strong>Saved public-data report.</strong> Real GitHub data and "
            f"{source_count} public source link{'s' if source_count != 1 else ''}, captured "
            f"{esc(format_generated_at(assessment.generated_at))}. Run a live analysis to refresh with Tavily."
        )
    else:
        contributor_count = len(assessment.contributors)
        search_count = sum(len(item.search_queries) for item in assessment.contributors)
        source_count = sum(len(item.evidence) for item in assessment.contributors)
        contributors_with_sources = sum(bool(item.evidence) for item in assessment.contributors)
        incomplete_count = sum(bool(item.error) for item in assessment.contributors)
        no_match_count = contributor_count - contributors_with_sources - incomplete_count
        text = (
            "<strong>Live analysis complete.</strong> GitHub loaded "
            f"{contributor_count} contributor{'s' if contributor_count != 1 else ''}; Tavily ran "
            f"{search_count} search{'es' if search_count != 1 else ''} and retained "
            f"{source_count} source{'s' if source_count != 1 else ''} for "
            f"{contributors_with_sources} contributor{'s' if contributors_with_sources != 1 else ''}. "
            f"{max(0, no_match_count)} had no retained match. Generated "
            f"{esc(format_generated_at(assessment.generated_at))}."
        )
    st.markdown(f'<div class="data-notice">{text}</div>', unsafe_allow_html=True)
    if assessment is not None and assessment.source_mode == "live" and assessment.errors:
        st.warning(
            f"Public-source search was incomplete for {len(assessment.errors)} "
            f"contributor{'s' if len(assessment.errors) != 1 else ''}. The remaining results are still shown."
        )
        with st.expander("View search errors"):
            for error in assessment.errors:
                st.text(error)


def render_empty_live_state() -> None:
    st.markdown(
        """
        <div class="panel empty-state">
            <h3>Run a live analysis</h3>
            <p>Add a Tavily API key in Settings, enter a public GitHub repository, and select Run analysis.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_repository_context(assessment: RepoAssessment) -> None:
    repo = assessment.repository
    source_count = sum(len(item.evidence) for item in assessment.contributors)
    source_label = "Sources in report"
    description = repo.description or "No repository description was provided."
    workflow_context = "Saved report" if assessment.source_mode == "snapshot" else "Live analysis"
    search_step = "Public-source review" if assessment.source_mode == "snapshot" else "Tavily search"
    st.markdown(
        f"""
        <div class="panel repo-panel">
            <div class="repo-top">
                <div>
                    <div class="repo-kicker">Repository</div>
                    <div class="repo-name">{esc(repo.full_name)}</div>
                    <div class="repo-description">{esc(description)}</div>
                </div>
                <div class="repo-facts">
                    <div class="repo-fact"><div class="repo-fact-value">{compact_number(repo.stars)}</div><div class="repo-fact-label">GitHub stars</div></div>
                    <div class="repo-fact"><div class="repo-fact-value">{compact_number(repo.forks)}</div><div class="repo-fact-label">Forks</div></div>
                    <div class="repo-fact"><div class="repo-fact-value">{len(assessment.contributors)}</div><div class="repo-fact-label">Contributors analyzed</div></div>
                    <div class="repo-fact"><div class="repo-fact-value">{source_count}</div><div class="repo-fact-label">{esc(source_label)}</div></div>
                </div>
            </div>
            <div class="pipeline" aria-label="Live analysis workflow">
                <span class="pipeline-context">{esc(workflow_context)}</span>
                <span class="pipeline-step"><span class="pipeline-dot" style="background:#FF7300"></span>GitHub data</span>
                <span class="pipeline-arrow">→</span>
                <span class="pipeline-step"><span class="pipeline-dot" style="background:#79DEEB"></span>{esc(search_step)}</span>
                <span class="pipeline-arrow">→</span>
                <span class="pipeline-step"><span class="pipeline-dot" style="background:#9BE6C1"></span>Human review</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_overview(assessment: RepoAssessment) -> None:
    contributors_with_sources = sum(bool(item.evidence) and not item.error for item in assessment.contributors)
    no_retained_matches = sum(not item.evidence and not item.error for item in assessment.contributors)
    incomplete_searches = sum(bool(item.error) for item in assessment.contributors)

    st.markdown(
        """
        <div class="tab-heading">
            <h2>Analysis summary</h2>
            <p>A concrete summary of the GitHub profiles and public sources in this report.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="panel status-strip">
            <div class="status-cell status-strong"><span class="status-name"><span class="status-marker"></span>Contributors with sources</span><span class="status-count">{contributors_with_sources}</span></div>
            <div class="status-cell status-limited"><span class="status-name"><span class="status-marker"></span>No retained matches</span><span class="status-count">{no_retained_matches}</span></div>
            <div class="status-cell status-partial"><span class="status-name"><span class="status-marker"></span>Search incomplete</span><span class="status-count">{incomplete_searches}</span></div>
        </div>
        <p class="status-caption">These are search outcomes, not ratings of the contributors. A source is retained only when its content contains enough identity details to plausibly match the GitHub account.</p>
        """,
        unsafe_allow_html=True,
    )

    if not assessment.contributors:
        st.info("No named, non-bot contributors were returned for this repository.")
        return

    source_column = "Sources"
    ordered = sorted(
        assessment.contributors,
        key=lambda contributor: -contributor.profile.contributions,
    )
    rows = []
    for item in ordered:
        outcome, _ = source_outcome(item)
        rows.append(
            {
                "Contributor": item.profile.display_name,
                "GitHub username": f"@{item.profile.login}",
                "Contributions": item.profile.contributions,
                source_column: len(item.evidence),
                "Public-source result": outcome,
            }
        )
    st.markdown('<div class="preview-label">Contributor preview</div>', unsafe_allow_html=True)
    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        height=min(52 + len(rows) * 35, 410),
        column_config={"Contributions": st.column_config.NumberColumn(format="localized")},
    )


def render_contributors(assessment: RepoAssessment) -> None:
    st.markdown(
        """
        <div class="tab-heading">
            <h2>Contributors</h2>
            <p>Select a contributor to review their GitHub profile and source-matching details.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not assessment.contributors:
        st.info("No named, non-bot contributors were returned for this repository.")
        return

    ordered = sorted(
        assessment.contributors,
        key=lambda item: -item.profile.contributions,
    )
    by_login = {item.profile.login: item for item in ordered}
    current_login = st.session_state.get("selected_login")
    if current_login not in by_login:
        preferred = preferred_contributor(assessment)
        current_login = preferred.profile.login if preferred else ordered[0].profile.login
    widget_key = selection_key(assessment, "contributor_choice")
    evidence_key = selection_key(assessment, "evidence_choice")
    if st.session_state.get(widget_key) not in by_login:
        st.session_state[widget_key] = current_login
    source_noun = "source"
    queue, detail = st.columns([0.82, 1.58], gap="large")
    with queue:
        st.markdown('<div class="workspace-label">Contributor list</div>', unsafe_allow_html=True)
        st.markdown('<div class="workspace-title">Select a contributor</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="workspace-caption">Each row shows the public-source search result for that GitHub account.</div>',
            unsafe_allow_html=True,
        )
        chosen_login = st.radio(
            "Contributor list",
            options=list(by_login),
            index=None,
            format_func=lambda login: (
                f"{by_login[login].profile.display_name} (@{login}) · "
                f"{by_login[login].profile.contributions:,} contributions · "
                f"{len(by_login[login].evidence)} {source_noun}"
                f"{'s' if len(by_login[login].evidence) != 1 else ''} · "
                f"{source_outcome(by_login[login])[0]}"
            ),
            label_visibility="collapsed",
            key=widget_key,
            on_change=sync_contributor_selection,
            args=(widget_key, evidence_key),
        )
        if chosen_login is None:
            chosen_login = current_login
        st.session_state.selected_login = chosen_login

    with detail:
        render_profile(assessment, by_login[chosen_login])


def render_profile(
    assessment: RepoAssessment,
    item: ContributorAssessment | None = None,
) -> None:
    item = item or selected_contributor(assessment)
    if item is None:
        st.info("There is no contributor profile in this report.")
        return

    profile = item.profile
    source_label = "Sources"
    status, status_class = source_outcome(item)
    outcome_explanation = source_outcome_explanation(item, assessment.source_mode)
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in item.reasons)
    if not reasons:
        reasons = "<li>No source-matching notes were recorded.</li>"
    st.markdown(
        f"""
        <div class="workspace-label">Selected contributor</div>
        <div class="profile-heading">
            <div><h2>{esc(profile.display_name)}</h2><div class="profile-handle">@{esc(profile.login)} · GitHub contributor</div></div>
            <span class="status-badge {status_class}">{esc(status)}</span>
        </div>
        <div class="panel person-panel">
            <div class="person-facts">
                <div class="person-fact"><span class="field-label">Repository contributions</span><span class="field-value">{profile.contributions:,}</span></div>
                <div class="person-fact"><span class="field-label">{esc(source_label)}</span><span class="field-value">{len(item.evidence)}</span></div>
                <div class="person-fact"><span class="field-label">Public repositories</span><span class="field-value">{profile.public_repos:,}</span></div>
                <div class="person-fact"><span class="field-label">Followers</span><span class="field-value">{profile.followers:,}</span></div>
            </div>
            <div class="outcome-note"><strong>What this result means.</strong> {esc(outcome_explanation)}</div>
            <div class="detail-grid">
                <div><div class="detail-title">Why the app reported this result</div><ul class="detail-list">{reasons}</ul></div>
                <div>
                    <div class="detail-title">GitHub profile</div>
                    <div class="profile-row"><span>Bio</span><span>{esc(profile.bio or 'Not provided')}</span></div>
                    <div class="profile-row"><span>Organization</span><span>{esc(profile.company or 'Not provided')}</span></div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    github_url = safe_http_url(profile.html_url) if not assessment.synthetic else None
    if github_url:
        st.link_button("View GitHub profile", github_url)
    if item.error:
        st.warning(f"Public-source search did not complete for this contributor: {item.error}")


def source_row(item: object, synthetic: bool) -> str:
    title = esc(item.title)
    url = safe_http_url(item.url) if not synthetic else None
    title_markup = (
        f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{title}</a>'
        if url
        else title
    )
    match_text = f"{str(item.identity_match).title()} identity match"
    match_class = "match-exact" if str(item.identity_match).lower() == "exact" else "match-probable"
    return (
        '<div class="source-row">'
        '<div>'
        f'<div class="source-title">{title_markup}</div>'
        f'<div class="source-meta">{esc(item.category)} · {esc(item.source_domain)}</div>'
        f'<div class="source-excerpt">{esc(item.excerpt or "No excerpt was returned.")}</div>'
        '</div>'
        f'<span class="match-label {match_class}">{esc(match_text)}</span>'
        '</div>'
    )


def render_evidence(assessment: RepoAssessment) -> None:
    if not assessment.contributors:
        st.info("There are no contributors in this report.")
        return

    ordered = sorted(
        assessment.contributors,
        key=lambda contributor: (
            bool(contributor.evidence),
            len(contributor.evidence),
            contributor.profile.contributions,
        ),
        reverse=True,
    )
    by_login = {item.profile.login: item for item in ordered}
    contributor_key = selection_key(assessment, "contributor_choice")
    evidence_key = selection_key(assessment, "evidence_choice")
    current_login = st.session_state.get("selected_login")
    if current_login not in by_login:
        preferred = preferred_contributor(assessment)
        current_login = preferred.profile.login if preferred else ordered[0].profile.login
    if st.session_state.get(evidence_key) not in by_login:
        st.session_state[evidence_key] = current_login

    st.markdown(
        """
        <div class="tab-heading">
            <h2>Public-source evidence</h2>
            <p>Choose a contributor to inspect the real public sources in this report.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    chosen_login = st.selectbox(
        "Contributor to inspect",
        options=list(by_login),
        index=None,
        format_func=lambda login: (
            f"{by_login[login].profile.display_name} (@{login}) · "
            f"{len(by_login[login].evidence)} retained source"
            f"{'s' if len(by_login[login].evidence) != 1 else ''} · "
            f"{source_outcome(by_login[login])[0]}"
        ),
        key=evidence_key,
        on_change=sync_contributor_selection,
        args=(evidence_key, contributor_key),
    )
    if chosen_login is None:
        chosen_login = current_login
    st.session_state.selected_login = chosen_login
    item = by_login[chosen_login]

    source_summary = (
        f"{len(item.evidence)} source{'s' if len(item.evidence) != 1 else ''} "
        "retained after identity matching."
    )
    st.markdown(
        f"""
        <div class="tab-heading">
            <h2>Evidence for {esc(item.profile.display_name)}</h2>
            <p>{source_summary}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if item.error:
        st.warning(
            "The public-source search did not complete for this contributor. "
            "GitHub profile facts are still available; rerun the analysis to retry Tavily search."
        )
        st.caption(f"Technical detail: {item.error}")
    elif not item.evidence:
        explanation = source_outcome_explanation(item, assessment.source_mode)
        st.markdown(
            f"""
            <div class="panel empty-state">
                <h3>No retained matches for {esc(item.profile.display_name)}</h3>
                <p>{esc(explanation)}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        other_matches = [
            contributor for contributor in ordered if contributor.evidence and contributor is not item
        ]
        if other_matches:
            names = ", ".join(contributor.profile.display_name for contributor in other_matches[:3])
            st.info(
                f"Sources were retained for {names}. Choose that contributor above to inspect them."
            )
        if item.search_queries:
            st.markdown('<div class="searches-run"><h4>Searches run</h4></div>', unsafe_allow_html=True)
            for query in item.search_queries:
                st.code(query, language=None)
            st.caption(
                "Results without enough matching identity details were left out to avoid showing the wrong person."
            )
    else:
        source_origin = (
            "Saved public sources"
            if assessment.source_mode == "snapshot"
            else "Retained from Tavily results"
        )
        st.markdown(
            f'<div class="tavily-source-label">{esc(source_origin)}</div>',
            unsafe_allow_html=True,
        )
        rows = "".join(source_row(source, assessment.synthetic) for source in item.evidence)
        st.markdown(
            f'<div class="panel"><div class="source-list">{rows}</div></div>',
            unsafe_allow_html=True,
        )

    detail_label = (
        "Source details" if assessment.source_mode == "snapshot" else "Tavily search details"
    )
    with st.container(key="source_details_shell"):
        with st.expander(detail_label):
            if assessment.source_mode == "snapshot":
                st.caption(
                    "This saved report uses real public URLs. Use the reference queries below when "
                    "refreshing it with Tavily."
                )
            else:
                st.caption(
                    "Exact matches include a GitHub handle plus a name or repository reference. "
                    "Probable matches include fewer identity details and require manual confirmation."
                )
            if item.evidence or item.search_queries:
                st.markdown(
                    "**Reference queries**" if assessment.source_mode == "snapshot" else "**Queries**"
                )
                for query in item.search_queries:
                    st.code(query, language=None)

            if item.evidence:
                if assessment.source_mode == "snapshot":
                    detail_rows = [
                        {
                            "Source type": source.category,
                            "Domain": source.source_domain,
                            "Identity match": source.identity_match,
                        }
                        for source in item.evidence
                    ]
                else:
                    detail_rows = [
                        {
                            "Source type": source.category,
                            "Domain": source.source_domain,
                            "Identity match": source.identity_match,
                            "Tavily relevance": round(source.relevance, 3),
                            "Content extracted": "Yes" if source.extracted else "No",
                        }
                        for source in item.evidence
                    ]
                st.dataframe(detail_rows, hide_index=True, width="stretch")
            if assessment.source_mode == "live" and item.tavily_request_ids:
                st.markdown("**Tavily request IDs**")
                st.code("\n".join(item.tavily_request_ids), language=None)


def render_export(assessment: RepoAssessment) -> None:
    report = sidecar_json(assessment)
    filename = f"{assessment.repository.full_name.replace('/', '-')}-contributor-evidence.json"
    note = (
        "This saved report contains real public URLs and can be refreshed through a live analysis."
        if assessment.source_mode == "snapshot"
        else "This live export contains public analysis results and never includes API keys."
    )
    st.markdown(
        """
        <div class="tab-heading"><h2>Export</h2><p>Download the current report as structured JSON.</p></div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(border=True):
        st.markdown("### Contributor report")
        st.caption(note)
        st.download_button(
            "Download JSON",
            data=report,
            file_name=filename,
            mime="application/json",
            type="secondary",
        )
        st.markdown(
            """
            <div class="export-scope">
                <div class="scope-column">
                    <h4>Included</h4>
                    <ul>
                        <li>Repository and contributor profile facts</li>
                        <li>Retained source records and search trace</li>
                    </ul>
                </div>
                <div class="scope-column">
                    <h4>Not included</h4>
                    <ul>
                        <li>API keys or access tokens</li>
                        <li>Judgments about behavior, intent, or legal eligibility</li>
                    </ul>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with st.expander("Preview JSON"):
        st.code(report, language="json")


initialize_state()
inject_styles()
mode = render_header_and_settings()
run_clicked = render_repository_controls(mode)
if run_clicked:
    run_live_analysis()

assessment = sync_assessment(mode)
render_data_notice(assessment, mode)

if assessment is None:
    render_empty_live_state()
    st.stop()

render_repository_context(assessment)

overview_tab, contributors_tab, evidence_tab, export_tab = st.tabs(
    ["Overview", "Contributors", "Evidence", "Export"]
)
with overview_tab:
    render_overview(assessment)
with contributors_tab:
    render_contributors(assessment)
with evidence_tab:
    render_evidence(assessment)
with export_tab:
    render_export(assessment)
