import { fmtNum, groupPrs } from '../format';

test('PR lines are grouped per lift with equal rep maxes merged', () => {
  expect(groupPrs(['Squat: Estimated 1RM 282', 'Squat: 3RM 235', 'Squat: 4RM 235', 'Squat: 5RM 235', 'Squat: 6RM 235',
    'Bench Press: 1RM 210', 'Bench Press: 2RM 200', 'Box Jump: Best 26'])).toEqual([
    'Squat: e1RM 282 · 3-6RM 235',
    'Bench Press: 1RM 210 · 2RM 200',
    'Box Jump: Best 26',
  ]);
});

test('fmtNum', () => {
  expect([fmtNum(180), fmtNum(182.5), fmtNum(182.04)]).toEqual(['180', '182.5', '182']);
});
