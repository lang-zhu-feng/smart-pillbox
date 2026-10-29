import fs from "node:fs/promises";
import path from "node:path";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
import JSZip from "jszip";

const workspaceDir = "C:/Users/liuzhanfei/Documents/ChatGPT/智慧药盒";
const renderDir = path.join(workspaceDir, "renders");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const candidatePath = path.join(stagingDir, "智慧药盒_答辩高级动态版_candidate.pptx");
const outputPath = path.join(workspaceDir, "output", "智慧药盒_答辩高级动态版.pptx");

const projectRoot = "E:/学校课程/智慧城市";
const productPath = "C:/Users/liuzhanfei/Documents/xwechat_files/wxid_8nv2yikggw9722_7f56/temp/RWTemp/2026-10/9e20f478899dc29eb19741386f9343c8/2285f89a9ae2dc342126efdc2fcfb951.png";
const homePath = path.join(projectRoot, "微信小程序/Demo首页预览.png");
const flowPath = path.join(projectRoot, "项目文档/系统流程图总览.png");

const W = 1280;
const H = 720;
const C = {
  ink: "#07131F",
  ink2: "#0B1E2D",
  slate: "#203746",
  mist: "#EAF3F1",
  paper: "#F7FAF8",
  white: "#FFFFFF",
  teal: "#12B7A6",
  teal2: "#087E78",
  cyan: "#6DE2D6",
  amber: "#FFCB6B",
  coral: "#F27A67",
  muted: "#9DB2B8",
  line: "#31505E",
};

function rect(slide, x, y, w, h, fill, radius = 0, lineFill = "none", lineWidth = 0) {
  return slide.shapes.add({
    geometry: radius ? "roundRect" : "rect",
    position: { left: x, top: y, width: w, height: h },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
    ...(radius ? { borderRadius: "rounded-xl" } : {}),
  });
}

function text(slide, value, x, y, w, h, fontSize, color = C.white, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = value;
  shape.text.style = {
    typeface: opts.fontFamily || "Microsoft YaHei",
    fontSize,
    color,
    bold: Boolean(opts.bold),
    alignment: opts.alignment || "left",
    ...(opts.italic ? { italic: true } : {}),
  };
  return shape;
}

function line(slide, x, y, w, h, fill = C.line) {
  return rect(slide, x, y, w, h, fill, 0);
}

async function imageBlob(imagePath) {
  const bytes = await fs.readFile(imagePath);
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
}

async function addImage(slide, imagePath, x, y, w, h, fit = "contain") {
  const ext = path.extname(imagePath).toLowerCase();
  const contentType = ext === ".jpg" || ext === ".jpeg" ? "image/jpeg" : "image/png";
  return slide.images.add({
    blob: await imageBlob(imagePath),
    contentType,
    alt: path.basename(imagePath),
    fit,
    position: { left: x, top: y, width: w, height: h },
  });
}

function header(slide, kicker, title, page) {
  text(slide, kicker.toUpperCase(), 72, 46, 340, 22, 13, C.cyan, { bold: true });
  text(slide, title, 72, 74, 900, 52, 34, C.white, { bold: true });
  text(slide, String(page).padStart(2, "0"), 1168, 50, 40, 26, 16, C.cyan, { bold: true, alignment: "right" });
  line(slide, 72, 140, 1136, 1, C.line);
}

function note(slide, lines) {
  slide.speakerNotes.text = lines.join("\n");
  slide.speakerNotes.setVisible(true);
}

function dot(slide, x, y, r, fill, lineFill = "none", lineWidth = 0) {
  return slide.shapes.add({
    geometry: "ellipse",
    position: { left: x - r, top: y - r, width: r * 2, height: r * 2 },
    fill,
    line: { style: "solid", fill: lineFill, width: lineWidth },
  });
}

function glowNode(slide, x, y, label, accent = C.teal) {
  dot(slide, x, y, 12, accent);
  dot(slide, x, y, 22, "none", accent, 2);
  if (label) text(slide, label, x - 45, y + 24, 90, 22, 13, C.muted, { alignment: "center" });
}

async function addSlideTransitions(pptxPath) {
  const zip = await JSZip.loadAsync(await fs.readFile(pptxPath));
  const slideNames = Object.keys(zip.files)
    .filter((name) => /^ppt\/slides\/slide\d+\.xml$/.test(name))
    .sort((a, b) => Number(a.match(/slide(\d+)/)[1]) - Number(b.match(/slide(\d+)/)[1]));
  const transitionXml = [
    '<p:transition spd="med" advClick="1"><p:fade/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:push dir="l"/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:wipe dir="l"/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:push dir="r"/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:fade/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:push dir="l"/></p:transition>',
    '<p:transition spd="med" advClick="1"><p:wipe dir="l"/></p:transition>',
    '<p:transition spd="slow" advClick="1"><p:zoom dir="in"/></p:transition>',
  ];
  for (let index = 0; index < slideNames.length; index++) {
    const name = slideNames[index];
    const xml = await zip.file(name).async("string");
    if (xml.includes("<p:transition")) continue;
    const close = "</p:cSld>";
    const at = xml.indexOf(close);
    if (at < 0) continue;
    const next = xml.slice(0, at + close.length) + transitionXml[index % transitionXml.length] + xml.slice(at + close.length);
    zip.file(name, next);
  }
  for (const [slideNumber, phases] of [
    [1, await coverAnimationPhases(zip)],
    [8, await finaleAnimationPhases(zip)],
  ]) {
    const name = `ppt/slides/slide${slideNumber}.xml`;
    const xml = await zip.file(name).async("string");
    zip.file(name, xml.replace("</p:sld>", `${buildTimingXml(phases)}</p:sld>`));
  }
  // Keep the middle slides paced as a reveal: title, main content, then the takeaway.
  // This gives the deck a consistent presentation rhythm without hiding any content.
  for (let slideNumber = 2; slideNumber <= 7; slideNumber++) {
    const name = `ppt/slides/slide${slideNumber}.xml`;
    const xml = await zip.file(name).async("string");
    if (xml.includes("<p:timing>")) continue;
    const phases = await stagedAnimationPhases(zip, slideNumber);
    zip.file(name, xml.replace("</p:sld>", `${buildTimingXml(phases)}</p:sld>`));
  }
  await fs.writeFile(pptxPath, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

async function slideShapes(zip, number) {
  const xml = await zip.file(`ppt/slides/slide${number}.xml`).async("string");
  return [...xml.matchAll(/<p:sp>([\s\S]*?)<\/p:sp>/g)].map((match) => {
    const source = match[1];
    const id = Number(source.match(/<p:cNvPr id="(\d+)"/)?.[1]);
    const off = source.match(/<a:off x="(\d+)" y="(\d+)"/);
    const ext = source.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
    const geometry = source.match(/<a:prstGeom prst="([^"]+)"/)?.[1] || "";
    const words = [...source.matchAll(/<a:t>([\s\S]*?)<\/a:t>/g)].map((item) => item[1]).join("");
    return { id, x: Number(off?.[1] || 0), y: Number(off?.[2] || 0), w: Number(ext?.[1] || 0), h: Number(ext?.[2] || 0), geometry, words };
  }).filter((shape) => Number.isFinite(shape.id));
}

function buildTimingXml(phases) {
  let nextId = 3;
  const phaseXml = phases.filter((phase) => phase.length).map((phase) => {
    const effects = phase.map((shapeId) => {
      const effectId = nextId++;
      return `<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="${effectId}" dur="520"/><p:tgtEl><p:spTgt spid="${shapeId}"/></p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr></p:animEffect>`;
    }).join("");
    return `<p:par><p:cTn id="${nextId++}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>${effects}</p:childTnLst></p:cTn></p:par>`;
  }).join("");
  if (!phaseXml) return "";
  return `<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>${phaseXml}</p:childTnLst></p:cTn></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>`;
}

async function stagedAnimationPhases(zip, slideNumber) {
  const shapes = await slideShapes(zip, slideNumber);
  // Coordinates are EMU values on a 16:9 slide. The bands match the visual rhythm
  // used by the deck: header, main composition, and closing annotation.
  const bands = [
    shapes.filter((shape) => shape.y < 1_650_000),
    shapes.filter((shape) => shape.y >= 1_650_000 && shape.y < 5_250_000),
    shapes.filter((shape) => shape.y >= 5_250_000),
  ];
  return bands.map((band) => band.map((shape) => shape.id)).filter((phase) => phase.length);
}

async function coverAnimationPhases(zip) {
  const shapes = await slideShapes(zip, 1);
  const title = shapes.filter((shape) => shape.words.includes("安心药伴")).map((shape) => shape.id);
  const subtitle = shapes.filter((shape) => shape.words.includes("独居老人智能用药与居家安全管理系统") || shape.words.includes("让每一份独自生活")).map((shape) => shape.id);
  const network = shapes.filter((shape) => shape.y > 4_750_000 && (shape.geometry === "ellipse" || shape.h <= 25_000)).map((shape) => shape.id);
  return [title, network, subtitle];
}

async function finaleAnimationPhases(zip) {
  const shapes = await slideShapes(zip, 8);
  const homes = shapes.filter((shape) => shape.geometry === "roundRect" && shape.w === 457_200 && shape.h === 342_900 && shape.x < 7_500_000 && shape.y < 4_500_000);
  const homeXs = new Set(homes.map((shape) => shape.x + shape.w / 2));
  const homeCenters = shapes.filter((shape) => shape.geometry === "ellipse" && shape.w === 133_350 && shape.h === 133_350 && [...homeXs].some((x) => Math.abs(x - shape.x - shape.w / 2) < 40_000));
  const homeLabels = shapes.filter((shape) => /^[A-F]$/.test(shape.words));
  const lines = shapes.filter((shape) => shape.geometry === "rect" && shape.h <= 25_000 && shape.w > 1_000_000 && shape.y < 4_500_000 && shape.x < 9_000_000);
  const dataDots = shapes.filter((shape) => shape.geometry === "ellipse" && shape.w === 38_100 && shape.h === 38_100);
  const trunk = shapes.filter((shape) => shape.geometry === "rect" && shape.w <= 25_000 && shape.h > 800_000 && shape.x > 8_000_000);
  const hub = shapes.filter((shape) => (shape.geometry === "roundRect" && shape.x > 8_500_000) || shape.words.includes("健康中枢") || shape.words.includes("城市守护节点"));
  const closing = shapes.filter((shape) => shape.words.includes("每一个家庭") || shape.words.includes("让每一份独自生活"));
  return [
    [...homes, ...homeCenters, ...homeLabels].map((shape) => shape.id),
    [...lines, ...dataDots].map((shape) => shape.id),
    [...trunk, ...hub].map((shape) => shape.id),
    closing.map((shape) => shape.id),
  ];
}

async function build() {
  await fs.mkdir(renderDir, { recursive: true });
  await fs.mkdir(stagingDir, { recursive: true });
  const presentation = Presentation.create({ slideSize: { width: W, height: H } });

  // 1. Cover
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.ink;
    // Network field: editable lines create a sense of motion across the cover.
    for (let i = 0; i < 8; i++) {
      line(slide, 72 + i * 145, 592 - i * 14, 108 + i * 12, 2, i % 2 ? C.teal2 : C.line);
      dot(slide, 92 + i * 145, 590 - i * 14, 5, i % 2 ? C.teal : C.cyan);
    }
    for (let i = 0; i < 5; i++) {
      line(slide, 760 + i * 72, 104 + i * 88, 2, 285 - i * 28, C.line);
      dot(slide, 761 + i * 72, 104 + i * 88, 4, C.cyan);
    }
    rect(slide, 72, 84, 112, 28, C.teal2, 14);
    text(slide, "SDG 3 · GOOD HEALTH", 88, 91, 250, 20, 12, C.white, { bold: true });
    text(slide, "安心药伴", 72, 176, 600, 90, 72, C.white, { bold: true });
    text(slide, "独居老人智能用药与居家安全管理系统", 78, 282, 740, 40, 24, C.cyan, { bold: true });
    text(slide, "让每一份独自生活，都连接在城市的守护之中。", 78, 346, 750, 34, 21, C.white);
    text(slide, "比赛答辩 · 队伍名称占位 · Logo 占位", 78, 634, 540, 24, 14, C.muted);
    rect(slide, 955, 510, 190, 70, C.ink2, 16, C.teal2, 1);
    text(slide, "LOGO\n占位", 955, 523, 190, 48, 18, C.cyan, { bold: true, alignment: "center" });
    note(slide, [
      "动态建议：标题 0.5 秒淡入，底部光点沿连线向右移动；保留 2 秒后进入下一页。",
      "素材缺口：队伍名称、Logo。封面可替换为最终城市网络视频的第一帧。",
    ]);
  }

  // 2. Problem / performance bridge
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.ink;
    header(slide, "01 / 问题", "漏服发生在家里，焦虑发生在远方", 2);
    text(slide, "表演引入 · 1 分钟", 72, 178, 300, 24, 16, C.amber, { bold: true });
    text(slide, "老人倒地、家属不知情、\n每一次延迟都在放大风险。", 72, 222, 500, 120, 34, C.white, { bold: true });
    text(slide, "我们先用夸张的舞台动作让问题被看见，再用系统把“看不见”变成可追踪的状态。", 72, 366, 520, 70, 19, C.muted);
    rect(slide, 720, 188, 420, 346, C.ink2, 24, C.line, 1);
    text(slide, "01", 760, 224, 80, 52, 32, C.coral, { bold: true });
    text(slide, "漏服", 760, 300, 260, 70, 56, C.white, { bold: true });
    text(slide, "无法及时被家属知道", 764, 386, 300, 30, 22, C.cyan, { bold: true });
    line(slide, 764, 448, 290, 2, C.coral);
    text(slide, "情景：问题发生在家庭，信息却断在家门外", 764, 472, 340, 28, 14, C.muted);
    glowNode(slide, 1130, 238, "家庭", C.coral);
    glowNode(slide, 1130, 470, "家属", C.cyan);
    line(slide, 1130, 260, 0, 180, C.line);
    note(slide, [
      "舞台口径：演示中“打开药格”即将本次任务标记为完成，这是本项目的演示规则。",
      "表演提示：抽搐动作应夸张但保持安全，服药用空道具或切镜完成，不呈现为现实急救建议。",
    ]);
  }

  // 3. Research framework placeholder
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.mist;
    text(slide, "02 / 调研框架", 72, 46, 340, 22, 13, C.teal2, { bold: true });
    text(slide, "先把真实需求问清楚", 72, 74, 900, 52, 34, C.ink, { bold: true });
    text(slide, "本页先留框架，后续把访谈记录、观察照片和需求原话替换进来。", 72, 136, 900, 26, 17, C.slate);
    const xs = [72, 434, 796];
    const titles = ["访谈", "观察", "归纳"];
    const subs = ["老人 / 家属 / 社区人员", "服药提醒 / 开盒 / 异常", "需求优先级 / 场景边界"];
    const accents = [C.teal, C.amber, C.coral];
    for (let i = 0; i < 3; i++) {
      rect(slide, xs[i], 234, 310, 258, C.paper, 20, "#D6E4E1", 1);
      rect(slide, xs[i] + 26, 260, 54, 8, accents[i], 4);
      text(slide, String(i + 1).padStart(2, "0"), xs[i] + 26, 294, 60, 44, 24, accents[i], { bold: true });
      text(slide, titles[i], xs[i] + 26, 356, 240, 42, 30, C.ink, { bold: true });
      text(slide, subs[i], xs[i] + 26, 412, 250, 32, 16, C.slate);
      text(slide, "素材占位", xs[i] + 26, 454, 200, 22, 13, C.muted);
    }
    line(slide, 382, 366, 40, 2, C.teal2);
    line(slide, 744, 366, 40, 2, C.teal2);
    text(slide, "待补：访谈人数、原话、观察照片、需求排序依据", 72, 584, 700, 26, 17, C.teal2, { bold: true });
    note(slide, ["动画建议：三个模块按“访谈 → 观察 → 归纳”依次擦除进入。", "素材缺口：调研对象、访谈记录、照片或问卷摘要。"]);
  }

  // 4. Goals with product hero
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.ink;
    header(slide, "03 / 目标", "把一次服药，变成一条可被看见的守护链", 4);
    text(slide, "老人端不增加学习负担，家属端看见关键状态，系统端保留可追踪记录。", 72, 176, 650, 34, 19, C.muted);
    await addImage(slide, productPath, 730, 188, 470, 280, "contain");
    rect(slide, 72, 250, 286, 150, C.ink2, 20, C.teal2, 1);
    text(slide, "提醒", 98, 278, 180, 34, 24, C.cyan, { bold: true });
    text(slide, "让老人只需要回应药盒。", 98, 326, 220, 40, 18, C.white);
    rect(slide, 382, 250, 286, 150, C.ink2, 20, C.amber, 1);
    text(slide, "联动", 408, 278, 180, 34, 24, C.amber, { bold: true });
    text(slide, "让开盒事件进入系统。", 408, 326, 220, 40, 18, C.white);
    rect(slide, 72, 442, 286, 150, C.ink2, 20, C.coral, 1);
    text(slide, "识别", 98, 470, 180, 34, 24, C.coral, { bold: true });
    text(slide, "让逾期和离线被看见。", 98, 518, 220, 40, 18, C.white);
    rect(slide, 382, 442, 286, 150, C.ink2, 20, C.cyan, 1);
    text(slide, "陪伴", 408, 470, 180, 34, 24, C.cyan, { bold: true });
    text(slide, "让远程关心有具体入口。", 408, 518, 220, 40, 18, C.white);
    text(slide, "概念设计效果图 · 21 格逻辑药盒 · 7 天 × 早中晚", 730, 496, 470, 26, 13, C.muted, { alignment: "center" });
    note(slide, ["动态建议：药盒先从右侧轻推入，四个目标沿着一条细线依次点亮。", "素材缺口：后续需要无水印药盒主图，并明确标注为“设计概念”。"]);
  }

  // 5. Solution / data loop
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.mist;
    text(slide, "04 / 解决方案", 72, 46, 340, 22, 13, C.teal2, { bold: true });
    text(slide, "从药格到家属端，信息不再断在家门口", 72, 74, 1000, 52, 34, C.ink, { bold: true });
    text(slide, "演示规则：检测到开盒事件 → 本次任务标记为完成；超过时间窗 → 生成异常提醒。", 72, 138, 1000, 26, 17, C.slate);
    const y = 300;
    const nodes = [
      [108, "计划", "家属设置\n用药时间", C.teal],
      [332, "药盒", "提醒 + 开盒\n21 格逻辑状态", C.amber],
      [556, "后端", "接收事件\n判断时间窗", C.coral],
      [780, "小程序", "状态同步\n历史可查", C.cyan],
      [1004, "家属", "异常可见\n及时回应", C.teal2],
    ];
    for (let i = 0; i < nodes.length; i++) {
      const [x, title, sub, accent] = nodes[i];
      dot(slide, x + 48, y, 48, C.paper, accent, 3);
      text(slide, title, x + 4, y - 16, 88, 26, 17, accent, { bold: true, alignment: "center" });
      text(slide, sub, x - 20, y + 68, 136, 44, 15, C.slate, { alignment: "center" });
      if (i < nodes.length - 1) {
        line(slide, x + 96, y - 1, 128, 3, C.teal2);
        dot(slide, x + 214, y, 5, C.teal2);
      }
    }
    rect(slide, 120, 506, 920, 68, C.paper, 18, "#D6E4E1", 1);
    text(slide, "提醒", 154, 527, 80, 24, 16, C.teal2, { bold: true });
    text(slide, "→", 236, 525, 36, 24, 18, C.slate, { bold: true });
    text(slide, "开盒", 288, 527, 80, 24, 16, C.amber, { bold: true });
    text(slide, "→", 370, 525, 36, 24, 18, C.slate, { bold: true });
    text(slide, "完成", 422, 527, 80, 24, 16, C.teal2, { bold: true });
    text(slide, "；未开盒", 516, 527, 100, 24, 16, C.coral, { bold: true });
    text(slide, "→", 620, 525, 36, 24, 18, C.slate, { bold: true });
    text(slide, "逾期", 672, 527, 80, 24, 16, C.coral, { bold: true });
    text(slide, "→", 754, 525, 36, 24, 18, C.slate, { bold: true });
    text(slide, "家属提醒", 806, 527, 140, 24, 16, C.teal2, { bold: true });
    note(slide, ["动画建议：五个节点按数据流方向依次出现；底部状态链使用 Morph 或擦除。", "技术栈：原生微信小程序 + FastAPI/SQLite（演示环境）+ ESP32 入口保留。"]);
  }

  // 6. Demo framework with app preview
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.ink;
    header(slide, "05 / 演示功能", "把一次演示，压缩成一条清晰的体验路径", 6);
    await addImage(slide, homePath, 72, 188, 310, 474, "contain");
    text(slide, "演示入口", 472, 194, 180, 26, 16, C.cyan, { bold: true });
    text(slide, "从首页进入家庭，再进入药盒与计划。", 472, 228, 560, 30, 21, C.white, { bold: true });
    const steps = [
      ["01", "首页", "家庭状态与今日入口"],
      ["02", "药盒", "7 × 3 逻辑格，早中晚"],
      ["03", "事件", "模拟开盒 / 逾期 / 离线"],
      ["04", "历史", "查看本次事件与时间"],
    ];
    for (let i = 0; i < steps.length; i++) {
      const yy = 302 + i * 74;
      dot(slide, 496, yy + 18, 18, i === 1 ? C.amber : C.teal2);
      text(slide, steps[i][0], 472, yy + 8, 48, 20, 11, C.white, { bold: true, alignment: "center" });
      line(slide, 530, yy + 18, 36, 2, C.line);
      text(slide, steps[i][1], 594, yy, 150, 28, 20, i === 1 ? C.amber : C.white, { bold: true });
      text(slide, steps[i][2], 754, yy + 2, 360, 24, 16, C.muted);
    }
    rect(slide, 472, 626, 646, 36, C.ink2, 12, C.line, 1);
    text(slide, "待替换：最终录屏 / 真机调试视频 / 硬件开盒镜头", 492, 635, 606, 18, 14, C.muted);
    note(slide, ["动画建议：左侧手机先出现，再按 01→04 的顺序点亮右侧节点。", "素材缺口：最终演示录屏、硬件开盒短视频、真机调试截图。"]);
  }

  // 7. Field test framework
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.mist;
    text(slide, "06 / 宣传与线下真实实验", 72, 46, 420, 22, 13, C.teal2, { bold: true });
    text(slide, "让系统走出屏幕，进入真实家庭", 72, 74, 1000, 52, 34, C.ink, { bold: true });
    text(slide, "本页先留框架：等硬件半成品和试用记录补齐后，再替换为真实照片与数据。", 72, 138, 1000, 26, 17, C.slate);
    rect(slide, 72, 222, 500, 290, C.paper, 20, "#D6E4E1", 1);
    text(slide, "真实实验", 104, 254, 220, 34, 24, C.ink, { bold: true });
    text(slide, "对象", 104, 322, 80, 24, 15, C.teal2, { bold: true });
    text(slide, "独居老人 / 家属 / 社区志愿者", 204, 322, 300, 24, 15, C.slate);
    text(slide, "场景", 104, 370, 80, 24, 15, C.teal2, { bold: true });
    text(slide, "早餐、午间、晚间三次提醒", 204, 370, 300, 24, 15, C.slate);
    text(slide, "指标", 104, 418, 80, 24, 15, C.teal2, { bold: true });
    text(slide, "开盒记录、提醒响应、异常可见性", 204, 418, 300, 24, 15, C.slate);
    rect(slide, 614, 222, 526, 290, C.ink, 20, C.teal2, 1);
    text(slide, "宣传路径", 646, 254, 220, 34, 24, C.white, { bold: true });
    text(slide, "线下展示药盒概念 → 现场演示小程序 → 收集反馈 → 优化硬件与交互", 646, 328, 420, 70, 22, C.cyan, { bold: true });
    line(slide, 646, 444, 414, 2, C.line);
    text(slide, "待补：实验照片、参与人数、反馈原话、前后对比", 646, 464, 420, 24, 14, C.muted);
    text(slide, "真实数据只写实测结果，不把模拟数据写成成果。", 72, 594, 700, 26, 17, C.coral, { bold: true });
    note(slide, ["动画建议：先出现家庭场景关键词，再出现“对象—场景—指标”三行。", "素材缺口：真实实验照片、参与对象、指标记录和反馈。"]);
  }

  // 8. Conclusion network
  {
    const slide = presentation.slides.add();
    slide.background.fill = C.ink;
    text(slide, "07 / 反思与总结", 72, 46, 420, 22, 13, C.cyan, { bold: true });
    text(slide, "连接，不是替代照护", 72, 74, 800, 52, 34, C.white, { bold: true });
    text(slide, "我们把一次开盒事件，做成家属能回应、城市能看见的健康信号。", 72, 138, 860, 28, 18, C.muted);
    // Network outro composition: multiple homes converge to a city health hub.
    const hubX = 1020;
    const hubY = 338;
    rect(slide, hubX - 72, hubY - 90, 144, 180, C.teal2, 18, C.cyan, 2);
    rect(slide, hubX - 42, hubY - 40, 84, 112, C.ink2, 10, C.cyan, 1);
    text(slide, "健康\n中枢", hubX - 42, hubY - 8, 84, 60, 23, C.cyan, { bold: true, alignment: "center" });
    text(slide, "城市守护节点", hubX - 82, hubY + 110, 164, 22, 14, C.muted, { alignment: "center" });
    const homes = [
      [260, 270, "A"], [420, 190, "B"], [520, 390, "C"], [330, 456, "D"], [670, 250, "E"], [720, 430, "F"],
    ];
    for (const [x, y, label] of homes) {
      rect(slide, x - 24, y - 18, 48, 36, C.ink2, 8, C.teal2, 1);
      text(slide, label, x - 24, y - 10, 48, 20, 12, C.cyan, { bold: true, alignment: "center" });
      const trunkX = hubX - 104;
      line(slide, x + 26, y, trunkX - (x + 26), 2, C.line);
      line(slide, trunkX, Math.min(y, hubY), 2, Math.max(2, Math.abs(hubY - y)), C.line);
      dot(slide, x, y, 7, C.teal);
      dot(slide, x + (trunkX - x) * 0.36, y, 4, C.cyan);
    }
    text(slide, "每一个家庭，都是城市健康网络的一颗光点。", 72, 506, 720, 34, 22, C.white, { bold: true });
    text(slide, "让每一份独自生活，都连接在城市的守护之中。", 72, 566, 860, 38, 24, C.cyan, { bold: true });
    rect(slide, 72, 640, 210, 32, C.ink2, 16, C.teal2, 1);
    text(slide, "结尾视频待插入", 72, 648, 210, 18, 13, C.muted, { alignment: "center" });
    note(slide, [
      "结尾视频镜头：家庭光点 → 药盒/手机发光 → 线汇聚到健康服务中枢 → 镜头沿中枢塔体向上 → 网络向城市外展开。",
      "中文提示词：未来智慧城市夜景，多个不同家庭的暖色窗光与药盒、手机发出细线，线条从家庭向远处汇聚到一座城市健康服务中枢，镜头从中枢塔体正上方升起，网络向四周展开，科技产品发布会质感，蓝绿色科技光与暖金色生活光并存，镜头平稳推进，结尾形成完整城市健康网络，画面干净，高级，16:9，无文字无水印。",
      "English prompt: Futuristic smart city at night, many distinct homes with warm window lights, each home connected by thin luminous data lines from a smart pillbox or phone to a central urban health service hub. The camera rises directly above the hub tower, then the network expands outward across the city. Premium technology product launch aesthetic, cool teal data light balanced with warm golden home light, smooth cinematic camera movement, clean composition, high-end, 16:9, no text, no watermark.",
      "素材缺口：最终结尾视频或首帧城市图。当前网络结构为可编辑 PPT 图形，便于后续替换成视频。",
    ]);
  }

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    await fs.writeFile(path.join(renderDir, `${stem}.png`), new Uint8Array(await (await presentation.export({ slide, format: "png", scale: 1 })).arrayBuffer()));
  }

  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(candidatePath);
  await addSlideTransitions(candidatePath);
  console.log(JSON.stringify({ candidatePath, outputPath, slideCount: presentation.slides.items.length }));
}

build().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

