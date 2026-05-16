import Nav from "@/components/nav";
import Hero from "@/components/hero";
import VideoShowcase from "@/components/video-showcase";
import FeaturesBento from "@/components/features-bento";
import Pipeline from "@/components/pipeline";
import ToolsMarquee from "@/components/tools-marquee";
import Install from "@/components/install";
import Footer from "@/components/footer";

export default function Home() {
  return (
    <>
      <Nav />
      <main>
        <Hero />
        <VideoShowcase />
        <FeaturesBento />
        <Pipeline />
        <ToolsMarquee />
        <Install />
      </main>
      <Footer />
    </>
  );
}
