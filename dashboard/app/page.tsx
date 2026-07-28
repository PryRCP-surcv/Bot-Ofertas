import type { Metadata } from "next";

import { BotOfertasAdmin } from "./BotOfertasAdmin";

export const metadata: Metadata = {
  title: "Panel administrativo",
  description:
    "Panel local para administrar el monitor responsable de precios públicos en Perú.",
};

export default function Home() {
  return <BotOfertasAdmin />;
}
