import { Hero } from "@/components/hero";
import { Button } from "@/components/ui/button";

const plans = [
  { name: "Weekly loaf", price: "€9", blurb: "One classic sourdough every Saturday." },
  { name: "Family box", price: "€24", blurb: "Three loaves and a brioche, twice a week." },
];

export default function Home() {
  return (
    <main>
      <header className="flex items-center justify-between border-b px-6 py-4">
        <span className="font-semibold">Maison Levain</span>
        <nav className="flex gap-6 text-sm"><a href="#menu">Menu</a><a href="#pricing">Pricing</a></nav>
      </header>
      <Hero />
      <section id="pricing" className="mx-auto grid max-w-4xl gap-6 px-6 py-16 md:grid-cols-2">
        {plans.map((p) => (
          <div key={p.name} className="rounded-xl border p-6">
            <h3 className="text-xl font-semibold">{p.name}</h3>
            <p className="mt-2 text-3xl font-bold">{p.price}</p>
            <p className="mt-2 text-zinc-600">{p.blurb}</p>
            <Button className="mt-6 w-full">Subscribe</Button>
          </div>
        ))}
      </section>
      <section className="bg-zinc-100 px-6 py-20 text-center">
        <h2 className="text-3xl font-bold">Taste the difference this weekend</h2>
        <p className="mt-4 text-zinc-600">First delivery is free for new neighbours.</p>
        <Button asChild className="mt-8"><a href="/order">Claim my free loaf</a></Button>
      </section>
    </main>
  );
}
