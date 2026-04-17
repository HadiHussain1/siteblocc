(function(){
  const publicApi = (path) => path;
  const applyBtn = document.getElementById("applyMemberCode");
  if (!applyBtn) return;

  applyBtn.addEventListener("click", function () {
    const codeInput = document.getElementById("memberCodeInput");
    const messageBox = document.getElementById("memberStatusMessage");
    if (!codeInput || !messageBox) return;

    const code = codeInput.value.trim();

    if (code.length !== 16) {
        messageBox.innerHTML = "<span style='color:#ff6b6b'>Please enter a valid 16-character code.</span>";
        return;
    }

    fetch(publicApi("/verify-member-code"), {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({ code: code })
    })
    .then(res => res.json())
    .then(data => {
        if (data.valid) {
            messageBox.innerHTML =
                `<span style="color:#4CAF50">Welcome back, ${data.name}. Member benefits unlocked.</span>`;

            window.memberVerified = true;
            window.memberCode = code;
        } else {
            messageBox.innerHTML = `<span style="color:#ff6b6b">${data.message}</span>`;
        }
    });
  });
})();
