import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

const SITE_URL = "https://videopilot.dev";
const TITLE = "VideoPilot — Tell an agent. Get a finished video.";
const DESCRIPTION =
  "Open-source MCP server and CLI that lets any LLM turn raw screen recordings into narrated, edited MP4s. 20 tools, 400+ neural voices, local word-level transcription, ffmpeg under the hood.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: TITLE,
    template: "%s · VideoPilot",
  },
  description: DESCRIPTION,
  applicationName: "VideoPilot",
  keywords: [
    "VideoPilot",
    "MCP server",
    "Model Context Protocol",
    "video editing",
    "AI video",
    "agentic video",
    "ffmpeg",
    "neural TTS",
    "faster-whisper",
    "Edge TTS",
    "FCPXML",
    "EDL",
    "GitHub Copilot",
    "Claude",
    "Cursor",
  ],
  authors: [{ name: "VideoPilot contributors" }],
  creator: "VideoPilot contributors",
  openGraph: {
    type: "website",
    url: SITE_URL,
    title: TITLE,
    description: DESCRIPTION,
    siteName: "VideoPilot",
  },
  twitter: {
    card: "summary_large_image",
    title: TITLE,
    description: DESCRIPTION,
  },
  robots: {
    index: true,
    follow: true,
  },
  category: "technology",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0a0a0f",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="font-sans antialiased min-h-dvh bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}
