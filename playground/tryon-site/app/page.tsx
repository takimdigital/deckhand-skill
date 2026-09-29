import { HeroHeader as DuskHeroSection1Header } from "@/components/sections/tailark-oss-dusk-hero-section-1-header/tailark-oss-dusk-hero-section-1-header"
import { HeroVideoDialog as HeroVideoDialog } from "@/components/sections/magicui-hero-video-dialog/magicui-hero-video-dialog"
import { BentoGrid as BentoGrid } from "@/components/sections/magicui-bento-grid/magicui-bento-grid"
import MistPricing1 from "@/components/sections/tailark-oss-mist-pricing-1/tailark-oss-mist-pricing-1"
import DuskFaqs1 from "@/components/sections/tailark-oss-dusk-faqs-1/tailark-oss-dusk-faqs-1"
import DuskCallToAction1 from "@/components/sections/tailark-oss-dusk-call-to-action-1/tailark-oss-dusk-call-to-action-1"
import MistFooter1 from "@/components/sections/tailark-oss-mist-footer-1/tailark-oss-mist-footer-1"

export default function Page() {
  return (
    <main>
      <DuskHeroSection1Header />
      <HeroVideoDialog />
      <BentoGrid />
      <MistPricing1 />
      <DuskFaqs1 />
      <DuskCallToAction1 />
      <MistFooter1 />
    </main>
  );
}
