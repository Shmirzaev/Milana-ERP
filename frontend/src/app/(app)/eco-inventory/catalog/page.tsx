"use client";
import Link from "next/link";
import InventoryMasterDataPage from "../../inventory/master-data/page";
import { useSearchParams } from "next/navigation";
import { useT } from "@/lib/i18n";
import { ecoInventoryText } from "@/lib/ecoInventory";

export default function EcoMaterialCatalogPage() {
  const { lang } = useT();
  const searchParams = useSearchParams();
  return <div className="space-y-4">
    <Link className="btn" href={`/eco-inventory?kind=${searchParams.get("group") === "accessories" ? "accessory" : "fabric"}`}>
      {ecoInventoryText(lang).title}
    </Link>
    <InventoryMasterDataPage />
  </div>;
}
