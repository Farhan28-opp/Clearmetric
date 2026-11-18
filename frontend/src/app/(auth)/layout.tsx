import { Logo } from "@/components/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1.1fr]">
      <main className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">{children}</div>
      </main>
      <aside className="hidden flex-col justify-end bg-ink p-12 text-white lg:flex" aria-hidden>
        <p className="max-w-md font-serif text-[28px] leading-snug">“Which region contributed most to the decrease in profit?”</p>
        <div className="mt-6 max-w-md space-y-2 border-l border-white/20 pl-4 text-sm text-white/75">
          <p>Total Profit fell between the two most recent months.</p>
          <p>The answer names the region, its share of the change and the method used, with the query one click away.</p>
        </div>
      </aside>
    </div>
  );
}
