"""End-to-end walk-through of the jury demonstration against running servers.

Usage:  python e2e/jury_demo.py [base_url] [--chrome /path/to/chrome] [--shots dir]
Requires: pip install playwright (and `playwright install chromium`, or pass --chrome)."""
import argparse
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

p = argparse.ArgumentParser()
p.add_argument("base", nargs="?", default="http://localhost:3000")
p.add_argument("--chrome", default=None)
p.add_argument("--shots", default="e2e/screenshots")
p.add_argument("--headed", action="store_true")
a = p.parse_args()
SHOTS = Path(a.shots)
SHOTS.mkdir(parents=True, exist_ok=True)
EMAIL = f"jury{int(time.time())}@example.com"
results: list[tuple[str, bool, str]] = []


def step(name):
    def deco(fn):
        def run(page):
            try:
                fn(page)
                results.append((name, True, ""))
                print(f"PASS  {name}")
            except Exception as e:  # noqa: BLE001
                results.append((name, False, str(e).splitlines()[0][:300]))
                print(f"FAIL  {name}: {str(e).splitlines()[0][:300]}")
                page.screenshot(path=str(SHOTS / f"fail_{len(results):02d}.png"), full_page=True)
                raise
        return run
    return deco


def shot(page, name):
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)


def ask(page, q, expect_kind="answer"):
    before = page.locator("article[aria-label='Answer']").count()
    page.get_by_label(re.compile("Ask a question about")).fill(q)
    page.get_by_role("button", name="Ask", exact=True).click()
    expect(page.locator("article[aria-label='Answer']")).to_have_count(before + 1, timeout=30000)
    return page.locator("article[aria-label='Answer']").last


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=a.chrome, headless=not a.headed)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, accept_downloads=True)
    page = ctx.new_page()
    page.set_default_timeout(20000)

    @step("Public website: home, product and navigation")
    def public(page):
        page.goto(a.base)
        expect(page.get_by_role("heading", level=1)).to_contain_text("Your business data has answers")
        expect(page.get_by_text("Computed live from")).to_be_visible(timeout=15000)
        page.get_by_role("tab", name="Why profit fell").click()
        expect(page.get_by_text("accounts for")).to_be_visible()
        shot(page, "01_home")
        for path, h in [("/product", "How ClearMetric is put together"), ("/features", "Features"), ("/solutions", "Where ClearMetric fits"),
                        ("/how-it-works", "How it works"), ("/trust", "Trust and privacy"), ("/contact", "Contact")]:
            page.goto(a.base + path)
            expect(page.get_by_role("heading", level=1)).to_contain_text(h)
        page.get_by_label("Name").fill("Jury Member")
        page.get_by_label("Work email").fill("jury@example.com")
        page.get_by_label("Message").fill("Interested in a demonstration for my shop.")
        page.get_by_role("button", name="Send message").click()
        expect(page.get_by_text("Message received")).to_be_visible()
    public(page)

    @step("Create account and workspace with currency")
    def signup(page):
        page.goto(a.base + "/signup")
        page.get_by_label("Full name").fill("Asha Rao")
        page.get_by_label("Work email").fill(EMAIL)
        page.get_by_label("Password").fill("demo-password-2026")
        page.get_by_role("button", name="Create account").click()
        page.wait_for_url("**/app/onboarding")
        page.get_by_label("Business or workspace name").fill("Asha Home Goods")
        page.get_by_label("Default currency").select_option("INR")
        shot(page, "02_onboarding_workspace")
        page.get_by_role("button", name="Create workspace").click()
        expect(page.get_by_role("heading", name="Choose some data to start with")).to_be_visible(timeout=20000)
    signup(page)

    @step("Load synthetic dataset, see profiling and schema")
    def load(page):
        page.get_by_role("button", name="Load demo data").click()
        expect(page.get_by_role("heading", name="Here’s what we found in your data")).to_be_visible(timeout=30000)
        expect(page.get_by_text("Data Quality Score")).to_be_visible()
        expect(page.get_by_role("cell", name="Net Revenue", exact=True)).to_be_visible()
        shot(page, "03_understand")
        page.get_by_role("button", name="Continue to business terms").click()
    load(page)

    @step("Confirm revenue and profit definitions")
    def terms(page):
        expect(page.get_by_label("Which column represents your net revenue (after discounts)?")).to_have_value("net_revenue")
        expect(page.get_by_label("Which column represents profit?")).to_have_value("profit")
        shot(page, "04_terms")
        page.get_by_role("button", name="Confirm and create metrics").click()
        expect(page.get_by_text(re.compile(r"Created \d+ verified metrics"))).to_be_visible(timeout=20000)
        page.get_by_role("button", name="See your first overview").click()
        expect(page.get_by_text("Interesting patterns")).to_be_visible()
        expect(page.locator("li", has_text="West accounts for").first).to_be_visible(timeout=30000)
        shot(page, "05_first_overview")
        page.get_by_role("button", name="Finish setup").click()
        page.wait_for_url("**/app/overview")
        expect(page.get_by_text("Net Revenue").first).to_be_visible(timeout=20000)
        shot(page, "06_overview")
    terms(page)

    @step("Analyst: top five products by net revenue, with chart and calculation")
    def q1(page):
        page.goto(a.base + "/app/analyst?new=1")
        page.wait_for_url(re.compile(r".*/app/analyst\?c=.*"))
        ans = ask(page, "Which five products generated the highest net revenue?")
        expect(ans).to_contain_text("The top 5 products by Net Revenue")
        expect(ans.locator("svg.recharts-surface")).to_be_visible()
        insp = page.get_by_role("complementary", name="Analysis inspector")
        expect(insp).to_contain_text("Net Revenue v1")
        expect(insp).to_contain_text("Records included")
        insp.get_by_role("button", name=re.compile("Generated query")).click()
        expect(insp.locator("pre", has_text="GROUP BY").first).to_be_visible()
        ans.get_by_role("radio", name="Table").click()
        expect(ans.locator("table")).to_contain_text("Share of total")
        shot(page, "07_analyst_top5")
    q1(page)

    @step("Analyst: follow-up resolves 'their' and computes contribution")
    def q2(page):
        ans = ask(page, "How much did their revenue contribute to total revenue?")
        expect(ans).to_contain_text("of total Net Revenue")
        expect(ans).to_contain_text("Resolved the reference to Product")
        shot(page, "08_analyst_contribution")
    q2(page)

    @step("Analyst: monthly revenue across all regions")
    def q3(page):
        ans = ask(page, "Compare monthly revenue across all regions.")
        expect(ans).to_contain_text("highest cumulative Net Revenue")
        expect(ans.locator(".recharts-line")).to_have_count(5)
        shot(page, "09_analyst_regions")
    q3(page)

    @step("Analyst: region that contributed most to the profit decrease")
    def q4(page):
        ans = ask(page, "Which region contributed most to the decrease in profit?")
        expect(ans).to_contain_text("West contributed most to the decrease")
        expect(ans).to_contain_text("not why")
        shot(page, "10_analyst_decomposition")
    q4(page)

    @step("Saved investigation persists after navigating away")
    def save(page):
        page.get_by_role("button", name="Save", exact=True).click()
        expect(page.get_by_role("button", name="Saved", exact=True)).to_be_visible()
        url = page.url
        page.goto(a.base + "/app/data")
        expect(page.get_by_role("heading", name="Data Hub")).to_be_visible()
        page.goto(a.base + "/app/overview")
        page.get_by_role("link", name=re.compile("Which five products")).first.click()
        expect(page.locator("article[aria-label='Answer']")).to_have_count(4, timeout=20000)
        assert page.url.split("c=")[1] == url.split("c=")[1]
    save(page)

    @step("Insights Center shows genuine observations with calculations")
    def insights(page):
        page.goto(a.base + "/app/insights")
        feed = page.get_by_role("list", name="Insight feed")
        expect(feed).to_contain_text("West accounts for")
        expect(feed).to_contain_text("unusually variable")
        expect(feed).to_contain_text("unusually large or small values")
        page.locator("ol[aria-label='Insight feed'] button", has_text="unusually large or small values").click()
        detail = page.locator("article[aria-label='Insight detail']")
        expect(detail).to_contain_text("Method")
        detail.get_by_role("button", name="Inspect supporting calculation").click()
        expect(detail).to_contain_text("Supporting calculation (recomputed now)")
        detail.get_by_role("button", name="View affected records").click()
        expect(detail).to_contain_text("Affected records")
        shot(page, "11_insights")
    insights(page)

    @step("Explore: visual builder with drill-down")
    def explore(page):
        page.goto(a.base + "/app/explore")
        page.get_by_label("Analysis type").select_option("breakdown")
        page.get_by_label("Dimension", exact=True).select_option("region")
        page.get_by_role("button", name="Run analysis").click()
        card = page.locator("section", has_text="Net Revenue: Breakdown by dimension by Region").first
        expect(card.locator("svg.recharts-surface")).to_be_visible(timeout=20000)
        card.locator(".recharts-bar-rectangle").first.click()
        expect(page.get_by_text("Drill path")).to_be_visible(timeout=20000)
        shot(page, "12_explore")
    explore(page)

    @step("Executive report with summary, PDF download")
    def report(page):
        page.goto(a.base + "/app/reports?new=executive")
        dlg = page.get_by_role("dialog")
        dlg.get_by_label("Title", exact=True).fill("October 2026 executive brief")
        dlg.get_by_label(re.compile("Include answers from an investigation")).select_option(index=1)
        dlg.get_by_role("button", name="Create report").click()
        page.wait_for_url(re.compile(r".*/app/reports/[a-f0-9]+"), timeout=30000)
        doc = page.get_by_role("article", name="Report document")
        expect(doc).to_contain_text("Main performance changes", timeout=30000)
        expect(doc).to_contain_text("Important limitations")
        expect(doc).to_contain_text("Suggested next investigations")
        shot(page, "13_report")
        with page.expect_download(timeout=60000) as d:
            page.get_by_role("button", name="PDF").click()
        path = SHOTS / "executive_brief.pdf"
        d.value.save_as(str(path))
        data = path.read_bytes()
        assert data[:4] == b"%PDF" and len(data) > 8000, f"unexpected PDF ({len(data)} bytes)"
    report(page)

    @step("Settings and activity are functional")
    def settings(page):
        page.goto(a.base + "/app/settings?tab=business")
        expect(page.get_by_label("Currency")).to_have_value("INR")
        page.goto(a.base + "/app/activity")
        expect(page.get_by_text(re.compile("Imported synthetic demo retail dataset"))).to_be_visible()
        shot(page, "14_activity")
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(a.base + "/app/overview")
        page.get_by_role("button", name="Open navigation").click()
        expect(page.get_by_role("dialog", name="Navigation")).to_be_visible()
        shot(page, "15_mobile_nav")
    settings(page)

    browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} steps passed")
sys.exit(1 if failed else 0)
