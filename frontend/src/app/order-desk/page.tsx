import type { Metadata } from "next";
import OrderDesk from "@/components/order-desk/OrderDesk";

export const metadata: Metadata = { title: "Order Desk · OMI", description: "獨立預審與執行工作台。Source / Fake 驗收，live broker 尚未部署。" };
export const dynamic = "force-dynamic";

export default function OrderDeskPage() {
  return <OrderDesk fakeConfigured={Boolean(process.env.OMI_ORDER_DESK_FAKE_PORT)} />;
}
