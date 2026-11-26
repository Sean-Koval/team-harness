import { confirmRemoval } from "./confirm-dialog.js";

const opener = document.querySelector("#remove");
opener.addEventListener("click", () => {
  confirmRemoval({
    title: "Delete Quarterly update?",
    opener,
    onConfirm: () => opener.closest("li").remove(),
    fallback: document.querySelector("#drafts"),
  });
});
