document.querySelectorAll('.animal').forEach((el) => {
  el.addEventListener('click', () => {
    const key = el.dataset.sound;
    const audio = new Audio(`sounds/${key}.mp3`);
    audio.play().catch(() => {});
  });
});