const $ = (selector) => document.querySelector(selector);
const panel = $('.images-panel');
const slotsElement = $('#image-slots');
const fileInput = $('#file-input');
const form = $('#generator-form');
const widthInput = $('#width-mm');
const heightInput = $('#height-mm');
const backgroundInput = $('#remove-background');
const modeInputs = [...document.querySelectorAll('[name=output-mode]')];
const generateButton = $('#generate-button');
const resultSection = $('#results');
const status = $('#status-message');
const error = $('#error-message');
let slots = [null, null];
let replaceIndex = null;
let busy = false;
let loading = false;
let result = null;

function element(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(options)) {
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

function icon(id) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
  use.setAttribute('href', `#${id}`);
  node.setAttribute('aria-hidden', 'true');
  node.append(use);
  return node;
}

function showError(message) {
  error.textContent = message;
  error.hidden = false;
}

function clearError() {
  error.hidden = true;
  error.textContent = '';
}

function dimensions() {
  const width = Number(widthInput.value);
  const height = Number(heightInput.value);
  if (![width, height].every((value) => Number.isFinite(value) && value >= 5 && value <= 300)) {
    return { error: '宽、高请输入 5–300 mm 之间的数字。' };
  }
  if (Math.round(width / 25.4 * 1440) * Math.round(height / 25.4 * 1440) > 40_000_000) {
    return { error: '这个尺寸超出了当前生成范围，请减小宽度或高度；100 × 100 mm 可以生成。' };
  }
  return { width, height };
}

function updateControls() {
  const locked = busy || loading;
  widthInput.disabled = heightInput.disabled = backgroundInput.disabled = locked;
  modeInputs.forEach((input) => { input.disabled = locked; });
  $('#clear-all').disabled = locked;
  $('#add-third').disabled = locked;
  for (const node of slotsElement.querySelectorAll('button')) {
    node.disabled = locked || node.dataset.unavailable === 'true';
  }
  for (const card of slotsElement.querySelectorAll('.slot')) {
    card.draggable = !locked && Boolean(slots[Number(card.dataset.index)]);
  }
  const filled = slots.filter(Boolean).length;
  generateButton.disabled = locked || filled !== slots.length || Boolean(dimensions().error);
  generateButton.classList.toggle('busy', busy);
  generateButton.querySelector('span').textContent = busy ? '正在生成…' : '生成打印文件';
  document.body.classList.toggle('generating', busy);
  $('#generate-hint').textContent = busy ? '正在计算条纹并导出，请稍候' : loading ? '正在读取图片…'
    : dimensions().error ? '请检查成品宽、高' : filled < slots.length
      ? `还需要 ${slots.length-filled} 张图片` : '彩色图与高度图将按当前尺寸生成';
}

function invalidate() {
  if (result) {
    status.textContent = '图片、顺序或尺寸已修改，请重新生成。';
  }
  result = null;
  resultSection.hidden = true;
  for (const link of resultSection.querySelectorAll('a')) link.removeAttribute('href');
  for (const image of resultSection.querySelectorAll('img')) image.removeAttribute('src');
}

function renderSlots() {
  slotsElement.replaceChildren();
  slotsElement.classList.toggle('three-slots', slots.length === 3);
  const names = slots.length === 2 ? ['左侧画面', '右侧画面'] : ['左侧画面', '正面画面', '右侧画面'];
  slots.forEach((item, index) => {
    const card = element('div', { class: `slot${item ? ' filled' : ''}`, 'data-index': index });
    card.append(element('div', { class: 'slot-top' }, [
      element('span', { class: 'slot-name', text: names[index] }),
      element('span', { class: 'slot-index', text: `0${index+1}` }),
    ]));
    const upload = element('button', { type: 'button', class: 'slot-upload',
      'data-action': 'choose', 'data-index': index,
      'aria-label': `${item ? '更换' : '上传'}${names[index]}` });
    if (item) {
      upload.append(element('img', { src: item.url, alt: `${names[index]}：${item.file.name}`, draggable: 'false' }),
        element('span', { class: 'replace-label', text: '更换图片' }));
    } else {
      upload.append(icon('uv-photo'), element('strong', { text: '点击上传' }), element('small', { text: '也可以拖入图片' }));
    }
    card.append(upload, element('div', { class: 'slot-file', title: item?.file.name || '',
      text: item ? item.file.name : '等待放入图片' }));
    const controls = element('div', { class: 'slot-controls' });
    if (item) {
      for (const [direction, label, unavailable] of [[-1, '← 前移', index === 0], [1, '后移 →', index === slots.length-1]]) {
        controls.append(element('button', { type: 'button', text: label, 'data-action': 'move',
          'data-index': index, 'data-direction': direction, 'data-unavailable': String(unavailable),
          'aria-label': `${names[index]}${direction < 0 ? '前移' : '后移'}` }));
      }
    }
    if (item || slots.length === 3) {
      controls.append(element('button', { type: 'button', text: slots.length === 3 ? '移除' : '清除', class: 'remove-slot',
        'data-action': 'remove', 'data-index': index, 'aria-label': `移除${names[index]}` }));
    }
    card.append(controls);
    slotsElement.append(card);
  });
  $('#mode-badge').textContent = slots.length === 3 ? '三画面 · 实验' : '双画面';
  $('#mode-badge').classList.toggle('experimental', slots.length === 3);
  $('#three-view-note').hidden = slots.length !== 3;
  $('#add-third').hidden = slots.length === 3;
  $('#clear-all').hidden = !slots.some(Boolean) && slots.length === 2;
  updateControls();
}

async function readFile(file) {
  if (!file.size || file.size > 20*1024*1024) throw new Error('每张图片不能为空，且不能超过 20 MB。');
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) && !/\.(png|jpe?g|webp)$/i.test(file.name)) {
    throw new Error('请上传 PNG、JPG 或 WebP 图片。');
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (Math.min(image.naturalWidth, image.naturalHeight) < 8 || image.naturalWidth*image.naturalHeight > 24_000_000) {
      throw new Error('单张图片至少为 8 × 8 像素，且不能超过 2400 万像素。');
    }
    return { file, url };
  } catch (err) {
    URL.revokeObjectURL(url);
    throw new Error(err instanceof DOMException ? '无法读取图片，请检查文件是否损坏。' : err.message);
  }
}

async function acceptFiles(files, index = null) {
  if (busy || loading || !files.length) return;
  clearError();
  if (files.length > 3) return showError('一次最多使用三张图片，请重新选择。');
  if (files.length === 1 && index === null && slots.length === 3 && slots.every(Boolean)) {
    return showError('已经放入三张图片。要更换图片，请点击对应画面。');
  }
  loading = true;
  updateControls();
  const prepared = [];
  try {
    for (const file of files) prepared.push(await readFile(file));
    if (prepared.length >= 2) {
      slots.filter(Boolean).forEach((slot) => URL.revokeObjectURL(slot.url));
      slots = prepared;
    } else if (index !== null) {
      if (slots[index]) URL.revokeObjectURL(slots[index].url);
      slots[index] = prepared[0];
    } else {
      const empty = slots.indexOf(null);
      if (empty >= 0) slots[empty] = prepared[0];
      else slots.push(prepared[0]);
    }
    invalidate();
  } catch (err) {
    prepared.forEach((slot) => URL.revokeObjectURL(slot.url));
    showError(err.message);
  } finally {
    loading = false;
    renderSlots();
  }
}

function moveSlot(from, to) {
  if (busy || loading || from === to || from < 0 || to < 0 || from >= slots.length || to >= slots.length) return;
  const [moving] = slots.splice(from, 1);
  slots.splice(to, 0, moving);
  invalidate();
  renderSlots();
  slotsElement.querySelector(`.slot[data-index="${to}"] .slot-upload`)?.focus();
}

slotsElement.addEventListener('click', (event) => {
  const button = event.target.closest('button[data-action]');
  if (!button || busy || loading) return;
  const index = Number(button.dataset.index);
  if (button.dataset.action === 'choose') {
    replaceIndex = index;
    fileInput.multiple = false;
    fileInput.click();
  } else if (button.dataset.action === 'move') {
    moveSlot(index, index + Number(button.dataset.direction));
  } else if (button.dataset.action === 'remove') {
    if (slots[index]) URL.revokeObjectURL(slots[index].url);
    if (slots.length === 3) slots.splice(index, 1);
    else slots[index] = null;
    invalidate();
    renderSlots();
  }
});

fileInput.addEventListener('change', () => {
  const files = [...fileInput.files];
  const index = replaceIndex;
  replaceIndex = null;
  fileInput.value = '';
  acceptFiles(files, index);
});

$('#add-third').addEventListener('click', () => {
  if (busy || loading || slots.length === 3) return;
  slots.splice(1, 0, null);
  invalidate();
  renderSlots();
  slotsElement.querySelector('.slot[data-index="1"] .slot-upload')?.focus();
});

$('#clear-all').addEventListener('click', () => {
  if (busy || loading) return;
  slots.filter(Boolean).forEach((slot) => URL.revokeObjectURL(slot.url));
  slots = [null, null];
  clearError();
  invalidate();
  renderSlots();
});

slotsElement.addEventListener('dragstart', (event) => {
  const card = event.target.closest('.slot');
  if (!card || busy || loading || !slots[Number(card.dataset.index)]) return event.preventDefault();
  event.dataTransfer.setData('application/x-uv-slot', card.dataset.index);
  event.dataTransfer.effectAllowed = 'move';
  card.classList.add('is-dragging');
});
slotsElement.addEventListener('dragover', (event) => {
  const card = event.target.closest('.slot');
  if (!card || busy || loading) return;
  event.preventDefault();
  slotsElement.querySelectorAll('.drop-target').forEach((node) => {
    if (node !== card) node.classList.remove('drop-target');
  });
  card.classList.add('drop-target');
});
slotsElement.addEventListener('dragleave', (event) => {
  if (!event.currentTarget.contains(event.relatedTarget)) {
    slotsElement.querySelectorAll('.drop-target').forEach((node) => node.classList.remove('drop-target'));
  }
});
slotsElement.addEventListener('drop', (event) => {
  const card = event.target.closest('.slot');
  if (!card) return;
  event.preventDefault();
  event.stopPropagation();
  panel.classList.remove('file-hover');
  slotsElement.querySelectorAll('.drop-target,.is-dragging').forEach((node) => node.classList.remove('drop-target', 'is-dragging'));
  if (event.dataTransfer.files.length) acceptFiles([...event.dataTransfer.files], Number(card.dataset.index));
  else {
    const origin = event.dataTransfer.getData('application/x-uv-slot');
    if (origin !== '') moveSlot(Number(origin), Number(card.dataset.index));
  }
});
document.addEventListener('dragend', () => {
  document.querySelectorAll('.drop-target,.is-dragging,.file-hover').forEach((node) => node.classList.remove('drop-target', 'is-dragging', 'file-hover'));
});
panel.addEventListener('dragover', (event) => {
  if (event.dataTransfer.types.includes('Files') && !busy && !loading) {
    event.preventDefault();
    panel.classList.add('file-hover');
  }
});
panel.addEventListener('dragleave', (event) => {
  if (!panel.contains(event.relatedTarget)) panel.classList.remove('file-hover');
});
panel.addEventListener('drop', (event) => {
  event.preventDefault();
  panel.classList.remove('file-hover');
  acceptFiles([...event.dataTransfer.files]);
});
document.addEventListener('dragover', (event) => {
  if (event.dataTransfer.types.includes('Files')) event.preventDefault();
});
document.addEventListener('drop', (event) => {
  if (event.dataTransfer.files.length) event.preventDefault();
});

for (const input of [widthInput, heightInput, backgroundInput, ...modeInputs]) {
  input.addEventListener('input', () => {
    clearError();
    input.removeAttribute('aria-invalid');
    invalidate();
    updateControls();
  });
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy || loading) return;
  clearError();
  const size = dimensions();
  if (size.error) return showError(size.error);
  if (slots.some((slot) => !slot)) return showError('请先放入全部画面。');
  invalidate();
  busy = true;
  updateControls();
  status.textContent = '正在生成配套的彩色图和高度图…';
  try {
    const data = new FormData();
    slots.forEach((slot) => data.append('files', slot.file));
    data.append('width_mm', String(size.width));
    data.append('height_mm', String(size.height));
    data.append('remove_background', String(backgroundInput.checked));
    data.append('output_mode', modeInputs.find((input) => input.checked).value);
    const response = await fetch('/api/uv/generate', { method: 'POST', headers: { 'X-UV-Local': '1' }, body: data });
    const body = await response.json();
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : '生成未完成，请检查图片和尺寸。');
    result = body;
    for (const role of ['color', 'depth', 'package']) {
      const anchor = $(`#download-${role}`);
      anchor.href = result.downloads[role];
      anchor.download = role === 'package' ? `uv-${result.width_mm}x${result.height_mm}mm.zip` : result.files[role].name;
    }
    const projectLink = $('#download-project');
    projectLink.hidden = !result.downloads.project;
    if (result.downloads.project) {
      projectLink.href = result.downloads.project;
      projectLink.download = result.files.project.name;
    }
    $('#color-preview').src = result.previews.color;
    $('#depth-preview').src = result.previews.depth;
    $('#result-summary').textContent = `${result.width_mm} × ${result.height_mm} mm · ${result.frame_count === 3 ? '三画面（实验）' : '双画面'} · 浮雕 0.8 mm`;
    $('#studio-settings').textContent = `尺寸 ${result.width_mm} × ${result.height_mm} mm · Customize Texture → Color Raised · Thickness 0.80 mm。项目打开后按实际平台重新定位、测高，不会自动打印。`;
    resultSection.hidden = false;
    status.textContent = result.experimental ? '三画面实验文件已生成，请先打印一枚小样。' : '彩色图和高度图已生成。';
    resultSection.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
  } catch (err) {
    status.textContent = '';
    showError(err instanceof TypeError ? '无法连接本地服务，请确认服务仍在运行后重试。' : err.message);
  } finally {
    busy = false;
    updateControls();
  }
});

renderSlots();
