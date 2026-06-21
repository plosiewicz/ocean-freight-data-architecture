import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Ocean Freight Data Architecture — right store per workload",
  description:
    "Hybrid OLAP + graph analytics for global ocean container logistics: BigQuery star schema for ETA reliability and dwell trends, ArangoDB property graph for chokepoint reachability and rerouting.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
