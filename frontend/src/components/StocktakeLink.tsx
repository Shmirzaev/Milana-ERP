"use client";
import Link from "next/link";
import { ClipboardCheck } from "lucide-react";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { stocktakeText } from "@/lib/stocktakeText";

export default function StocktakeLink() {
  const { me } = useMe();
  const { lang } = useT();
  return can(me, "storage.packages", "storage.shipment") ? (
    <Link className="btn" href="/warehouse-stock/count"><ClipboardCheck />{stocktakeText[lang].title}</Link>
  ) : null;
}
