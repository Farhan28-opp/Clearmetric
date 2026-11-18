import type { Metadata } from "next";
import { ButtonLink } from "@/components/ui";

export const metadata: Metadata = { title: "Solutions" };

const S = [
  { id: "retail", title: "Retail", who: "Shop owners and multi-store retailers", data: "Point-of-sale exports with date, store or region, product, quantity, price and discount.", qs: ["Which region contributed most to the decrease in profit last month?", "Which products have the lowest margin?", "Are discounts associated with lower margins?"] },
  { id: "ecommerce", title: "E-commerce", who: "Online stores and marketplace sellers", data: "Order exports with customer ID, channel, order value and fulfilment cost.", qs: ["How concentrated is revenue among our top customers?", "Compare marketplace and online-store revenue by month", "Which orders are unusually large?"] },
  { id: "sales-ops", title: "Sales operations", who: "Sales managers and revenue operations", data: "Deal or invoice records with rep, segment, region and close date.", qs: ["Compare this quarter with the previous quarter by region", "Which segment drove the change in bookings?", "Show monthly revenue for the top three reps"] },
  { id: "small-business", title: "Small businesses", who: "Owners who run the numbers themselves", data: "Any spreadsheet of sales, invoices or transactions.", qs: ["What were total sales and profit this year?", "Which month performed best?", "What can I analyse with this data?"] },
  { id: "analysts", title: "Business analysts", who: "Analysts who need answers others can audit", data: "Cleaned extracts from your warehouse or BI tool.", qs: ["Define a verified metric once and reuse it everywhere", "Inspect the query behind every chart", "Reproduce last month’s figures exactly"] },
  { id: "general", title: "General business data", who: "Anyone with a table of records", data: "Unfamiliar column names are fine: you confirm meanings and ClearMetric asks when unsure.", qs: ["What columns are present?", "How are values distributed?", "Which records differ most from normal?"] },
];

export default function SolutionsPage() {
  return (
    <div className="mx-auto max-w-6xl px-5 py-14">
      <h1 className="text-4xl font-semibold tracking-[-0.02em]">Where ClearMetric fits</h1>
      <p className="mt-3 max-w-2xl text-lg text-ink-2">Examples of the data and questions each kind of team brings. The answers depend on your data; ClearMetric makes no claims about results you will see.</p>
      <div className="mt-12 divide-y divide-line border-y border-line">
        {S.map((s) => (
          <section key={s.id} id={s.id} aria-labelledby={`${s.id}-h`} className="grid gap-6 py-8 md:grid-cols-[14rem_1fr_1.3fr]">
            <div><h2 id={`${s.id}-h`} className="text-xl font-semibold">{s.title}</h2><p className="mt-1 text-sm text-muted">{s.who}</p></div>
            <p className="text-sm leading-relaxed text-ink-2">{s.data}</p>
            <ul className="space-y-2">{s.qs.map((q) => <li key={q} className="font-serif text-[17px] leading-snug">“{q}”</li>)}</ul>
          </section>
        ))}
      </div>
      <div className="mt-12"><ButtonLink href="/signup" variant="primary">Try these questions on demo data</ButtonLink></div>
    </div>
  );
}
