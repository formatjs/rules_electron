window.desktop.read().then((result) => {
  document.querySelector('#result').textContent = JSON.stringify(result, null, 2);
  window.desktop.complete(result);
}).catch((error) => {
  document.querySelector('#result').textContent = String(error);
});
