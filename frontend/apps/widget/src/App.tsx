import { WidgetComponent } from './components/WidgetComponent';

const defaultConfig = {
  apiUrl: 'http://localhost:8000',
  brandName: '在线客服',
  welcomeMessage: '你好！有什么可以帮到您？',
  position: 'right' as const,
  themeColor: '#0052d9',
  zIndex: 9999,
};

const defaultSuggestions = [
  '你们的营业时间是什么？',
  '怎么退货？',
  '怎么联系人工客服？',
];

export function App() {
  return (
    <WidgetComponent
      config={defaultConfig}
      suggestions={defaultSuggestions}
    />
  );
}
