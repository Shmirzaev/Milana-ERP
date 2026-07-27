import type { Metadata } from "next";
import PresentationLanding from "@/components/presentation/PresentationLanding";

export const metadata: Metadata = {
  title: "Milana Ecosystem factory control system",
  description: "A customer-focused presentation of Milana Ecosystem for garment manufacturing control.",
};

export default function PresentationPage() {
  return <PresentationLanding />;
}
