import Link from "next/link";
import { Button } from "@/components/ui/button";

export function Hero() {
  return (
    <section className="mx-auto max-w-3xl px-6 py-24 text-center">
      <h1 className="text-5xl font-bold tracking-tight">
        Sourdough delivered <span className="text-amber-600">warm</span> to your door
      </h1>
      <p className="mt-6 text-lg text-zinc-600">
        Maison Levain bakes every loaf at 4am and delivers across Lyon before breakfast.
      </p>
      <div className="mt-10 flex justify-center gap-4">
        <Button asChild size="lg">
          <Link href="/order">Order your first loaf</Link>
        </Button>
        <Button asChild size="lg" variant="outline">
          <Link href="#menu">See the menu</Link>
        </Button>
      </div>
    </section>
  );
}
