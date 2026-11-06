import Swal from "sweetalert2";

export const alerts = {
  success: (title, text = "") =>
    Swal.fire({ icon: "success", title, text, confirmButtonColor: "#218653" }),

  error: (error) =>
    Swal.fire({
      icon: "error",
      title: "Unable to complete",
      text: error?.message || String(error),
      confirmButtonColor: "#218653"
    }),

  confirm: (title, text = "Please confirm this action.") =>
    Swal.fire({
      icon: "warning",
      title,
      text,
      showCancelButton: true,
      confirmButtonText: "Yes, continue",
      confirmButtonColor: "#218653"
    })
};
