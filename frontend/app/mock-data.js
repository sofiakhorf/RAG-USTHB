export const subjects = [
  { id: 'algorithms', code: 'L1', nameAr: 'الخوارزميات', nameEn: 'Algorithms' },
  { id: 'analysis', code: 'L1', nameAr: 'التحليل 1', nameEn: 'Analysis 1' },
  { id: 'algebra', code: 'L1', nameAr: 'الجبر 1', nameEn: 'Algebra 1' },
  { id: 'physics', code: 'L1', nameAr: 'الفيزياء 1', nameEn: 'Physics 1' },
]

export const initialDocuments = [
  {
    id: 'ch3-notes',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-25T18:00:00+01:00'),
    name: 'Ch3_Notes.pdf',
    fileType: 'PDF',
    sizeLabel: '2.4 MB',
    description: 'Lecture notes on algorithmic complexity and search methods.',
    pages: [
      {
        title: 'Binary Search',
        text: 'Binary search works on a sorted array, dividing the search space in half at each step until finding the target element.',
      },
      {
        title: 'Time Complexity',
        text: 'The number of search operations is logarithmic to the number of elements, resulting in a time complexity of O(log n).',
      },
    ],
  },
  {
    id: 'algorithms-l1',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-24T17:30:00+01:00'),
    name: 'Algorithms_L1.pdf',
    fileType: 'PDF',
    sizeLabel: '4.8 MB',
    description: 'First-year course syllabus guide for Algorithms and Data Structures.',
    pages: [
      {
        title: 'Linear Search',
        text: 'Linear search checks elements sequentially until a match is found. Data sorting is not required, and worst-case complexity is O(n).',
      },
      {
        title: 'Algorithm Selection',
        text: 'Choosing between linear and binary search depends on data order, size, and preprocessing costs.',
      },
    ],
  },
  {
    id: 'td02-exercises',
    subjectId: 'algorithms',
    updatedAtValue: Date.parse('2026-10-22T12:00:00+01:00'),
    name: 'TD02_Exercises.pdf',
    fileType: 'PDF',
    sizeLabel: '1.1 MB',
    description: 'Tutorial exercises and review instructions for Week 2.',
    pages: [
      {
        title: 'Recursion Exercises',
        text: 'Analyze the base case, then establish the recursive relation before computing algorithmic complexity.',
      },
      {
        title: 'Solution Review',
        text: 'Ensure every recursive call moves closer to the base case and that edge cases are fully covered.',
      },
    ],
  },
]

export const initialConversations = [
  { id: 'binary-search', title: 'Binary search complexity', updatedAt: 'Today · 10:42', updatedAtValue: Date.parse('2026-10-26T10:42:00+01:00'), subjectId: 'algorithms' },
  { id: 'recursion', title: 'Recursion exercises', updatedAt: 'Yesterday · 18:18', updatedAtValue: Date.parse('2026-10-25T18:18:00+01:00'), subjectId: 'algorithms' },
  { id: 'sorting', title: 'Sorting algorithms review', updatedAt: 'Mar 12 · 14:05', updatedAtValue: Date.parse('2026-03-12T14:05:00+01:00'), subjectId: 'algorithms' },
]

export const initialMessagesByConversation = {
  'binary-search': [
    { id: 'binary-user-1', role: 'user', text: 'What is the time complexity of the binary search algorithm?' },
    {
      id: 'binary-assistant-1',
      role: 'assistant',
      text: 'The time complexity of binary search is O(log n) because it halves the search space with every step. The data must be sorted beforehand for it to work properly.',
      sourceIds: ['ch3-notes'],
    },
    { id: 'binary-user-2', role: 'user', text: 'Could you explain the key difference compared to linear search?' },
    {
      id: 'binary-assistant-2',
      role: 'assistant',
      text: 'Certainly. Linear search inspects items sequentially with O(n) complexity, whereas binary search is significantly faster with O(log n) complexity but requires a sorted array. Use binary search when data is ordered and large, and linear search for small or unsorted datasets.',
      sourceIds: ['algorithms-l1'],
    },
  ],
  recursion: [
    { id: 'recursion-user-1', role: 'user', text: 'What is meant by recursion in programming?' },
    {
      id: 'recursion-assistant-1',
      role: 'assistant',
      text: 'Recursion occurs when a function calls itself to solve a smaller instance of the same problem. It requires a clear base case to terminate execution.',
      sourceIds: ['td02-exercises'],
    },
  ],
  sorting: [
    { id: 'sorting-user-1', role: 'user', text: 'What is the difference between Selection Sort and Merge Sort?' },
    {
      id: 'sorting-assistant-1',
      role: 'assistant',
      text: 'Selection sort selects the smallest element in each pass and operates with O(n²) time complexity. Merge sort uses divide-and-conquer to achieve O(n log n) complexity with additional memory overhead.',
      sourceIds: ['algorithms-l1'],
    },
  ],
}