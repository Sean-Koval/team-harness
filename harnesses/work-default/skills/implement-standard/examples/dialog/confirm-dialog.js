export function confirmRemoval({ title, opener, onConfirm, fallback }) {
  const dialog = document.createElement("dialog");
  dialog.innerHTML = `
    <form method="dialog">
      <h2 id="confirm-title"></h2>
      <button value="cancel" autofocus>Cancel</button>
      <button value="confirm">Delete</button>
    </form>`;
  dialog.setAttribute("aria-labelledby", "confirm-title");
  dialog.querySelector("h2").textContent = title;
  dialog.addEventListener("close", () => {
    if (dialog.returnValue === "confirm") onConfirm();
    dialog.remove();
    (opener.isConnected ? opener : fallback).focus();
  }, { once: true });
  document.body.append(dialog);
  dialog.showModal();
}
