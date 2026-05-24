import { redirect } from "next/navigation";

export default function EmployeesRedirectPage() {
  redirect("/admin/employees");
}
