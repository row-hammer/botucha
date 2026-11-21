import assert from "node:assert/strict";
import { test } from "node:test";
import { layoutPeople, NODE_H, NODE_W } from "../src/lib/people-layout.ts";

const person = (id, user_id = null) => ({ id, name: `P${id}`, aliases: [], user_id, fact_count: 0 });
const graph = {
  people: [1, 2, 3, 4, 5, 6, 7, 8].map((i) => person(i, i < 3 ? i : null)),
  relations: [
    { id: 1, a: 1, rel: "darbdavys", b: 2 },
    { id: 2, a: 2, rel: "draugas", b: 3 },
    { id: 3, a: 1, rel: "brolis", b: 4 },
  ],
  comentions: [{ a: 3, b: 5, n: 2 }],
};

const overlap = (p, q) => Math.abs(p.x - q.x) < NODE_W && Math.abs(p.y - q.y) < NODE_H;

test("no two people overlap", () => {
  const pos = layoutPeople(graph);
  const all = Object.values(pos);
  assert.equal(all.length, 8);
  for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++) assert.ok(!overlap(all[i], all[j]));
});

test("people with no links sit below the linked ones", () => {
  const pos = layoutPeople(graph);
  const linkedBottom = Math.max(...[1, 2, 3, 4, 5].map((i) => pos[i].y));
  for (const i of [6, 7, 8]) assert.ok(pos[i].y > linkedBottom, `P${i} should be below`);
});

test("linked people flow left to right with room for labels", () => {
  const pos = layoutPeople(graph);
  assert.ok(pos[2].x - pos[1].x >= NODE_W + 60, "a relation label needs space between the boxes");
});

test("the same graph always gives the same layout", () => {
  assert.deepEqual(layoutPeople(graph), layoutPeople(graph));
});

test("saved positions win over the layout", () => {
  const pos = layoutPeople(graph, { 3: { x: 999, y: -5 } });
  assert.deepEqual(pos[3], { x: 999, y: -5 });
});

test("an empty graph is fine", () => {
  assert.deepEqual(layoutPeople({ people: [], relations: [], comentions: [] }), {});
});
