import { mkdir, writeFile } from 'node:fs/promises';
import { createElement as h } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ActivityCalendar } from 'react-activity-calendar';

const theme = {
  light: ['#eff2f5', '#aceebb', '#4ac26b', '#2da44e', '#116329'],
  dark: ['#151b23', '#033a16', '#196c2e', '#2ea043', '#56d364'],
};
const levels = ['NONE', 'FIRST_QUARTILE', 'SECOND_QUARTILE', 'THIRD_QUARTILE', 'FOURTH_QUARTILE'];

function renderCalendar(calendar, colorScheme) {
  const data = calendar.weeks.flatMap(week => week.contributionDays).map(day => ({
    date: day.date,
    count: day.contributionCount,
    level: levels.indexOf(day.contributionLevel),
  }));
  const markup = renderToStaticMarkup(h(ActivityCalendar, {
    data, theme, colorScheme,
    blockSize: 10, blockMargin: 3, blockRadius: 2, fontSize: 12,
    showWeekdayLabels: ['mon', 'wed', 'fri'],
    showColorLegend: false, showTotalCount: false,
  }));
  const chart = markup.match(/<svg\b[^>]*width="(\d+)"[^>]*height="(\d+)"[\s\S]*?<\/svg>/);
  if (!chart) throw new Error('Calendar renderer did not return an SVG.');
  const width = Number(chart[1]) + 72;
  const height = Number(chart[2]) + 90;
  const foreground = colorScheme === 'dark' ? '#f0f6fc' : '#1f2328';
  const border = colorScheme === 'dark' ? '#3d444d' : '#d1d9e0';
  const background = colorScheme === 'dark' ? '#0d1117' : '#ffffff';
  const legend = h('g', { transform: `translate(${width - 180}, ${height - 22})` },
    h('text', { x: 0, y: 9 }, 'Less'),
    ...theme[colorScheme].map((fill, i) => h('rect', {
      key: i, x: 34 + i * 13, width: 10, height: 10, rx: 2, fill,
      stroke: border, strokeWidth: 0.5,
    })),
    h('text', { x: 104, y: 9 }, 'More'));
  const frame = renderToStaticMarkup(h('svg', {
    xmlns: 'http://www.w3.org/2000/svg', width, height,
    viewBox: `0 0 ${width} ${height}`, role: 'img',
    'aria-label': `${calendar.totalContributions} contributions in the last year`,
    style: { fontFamily: '-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif', fontSize: 12, color: foreground, fill: foreground },
  },
  h('title', null, `${calendar.totalContributions} contributions in the last year`),
  h('rect', { width, height, rx: 6, fill: background }),
  h('text', { x: 1, y: 20, fontSize: 16 }, `${calendar.totalContributions.toLocaleString('en-US')} contributions in the last year`),
  h('rect', { x: 0.5, y: 33.5, width: width - 1, height: height - 34, rx: 6, fill: 'none', stroke: border }),
  h('g', { transform: 'translate(52, 47)', dangerouslySetInnerHTML: { __html: chart[0].replace('<svg ', '<svg overflow="visible" ') } }),
  legend));
  return `${frame}\n`;
}

if (!process.env.GH_TOKEN) throw new Error('Set the CONTRIBUTIONS_TOKEN repository secret to your own PAT with read:user scope.');
const response = await fetch('https://api.github.com/graphql', {
  method: 'POST',
  headers: { Authorization: `Bearer ${process.env.GH_TOKEN}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ query: `query {
    viewer {
      login
      contributionsCollection {
        contributionCalendar {
          totalContributions
          weeks { contributionDays { date contributionCount contributionLevel } }
        }
      }
    }
  }` }),
  signal: AbortSignal.timeout(30000),
});
if (!response.ok) throw new Error(`GitHub API returned HTTP ${response.status}.`);
const result = await response.json();
if (result.errors?.length) throw new Error('GitHub could not return the contribution calendar. Check the token permissions.');
const viewer = result.data?.viewer;
if (viewer?.login.toLowerCase() !== process.env.PROFILE_USER?.toLowerCase()) {
  throw new Error('CONTRIBUTIONS_TOKEN must belong to the profile repository owner.');
}
const calendar = viewer.contributionsCollection.contributionCalendar;
await mkdir('assets', { recursive: true });
for (const scheme of ['light', 'dark']) {
  await writeFile(`assets/contributions-${scheme}.svg`, renderCalendar(calendar, scheme));
}
