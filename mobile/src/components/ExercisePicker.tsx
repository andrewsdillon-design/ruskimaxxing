// A searchable list of every exercise in the catalog, grouped main lifts / variations / accessories / jumps.
import { useState } from 'react';
import { FlatList, Modal, Pressable, StyleSheet, TextInput, View } from 'react-native';
import { CATALOG, type Category } from '../core/exercises';
import { fonts, useTheme } from '../theme';
import { Button, Display, T } from './ui';

const ORDER: Category[] = ['main', 'variation', 'accessory', 'plyo'];
const HEADINGS: Record<Category, string> = { main: 'Main lifts', variation: 'Variations', accessory: 'Accessories', plyo: 'Jumps' };

export function ExercisePicker({ visible, onPick, onClose }: { visible: boolean; onPick: (name: string) => void; onClose: () => void }) {
  const { c } = useTheme();
  const [q, setQ] = useState('');
  const all = [...CATALOG.values()].filter((e) => e.name.toLowerCase().includes(q.trim().toLowerCase()));
  const rows: ({ heading: string } | { name: string; parent: string | null })[] = [];
  for (const cat of ORDER) {
    const list = all.filter((e) => e.category === cat);
    if (list.length) rows.push({ heading: HEADINGS[cat] }, ...list.map((e) => ({ name: e.name, parent: e.parent })));
  }
  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose} presentationStyle="pageSheet">
      <View style={[st.sheet, { backgroundColor: c.bg }]}>
        <Display size={20}>Choose an exercise</Display>
        <TextInput
          value={q}
          onChangeText={setQ}
          placeholder="Search"
          placeholderTextColor={c.muted}
          autoFocus
          style={[st.search, { backgroundColor: c.field, borderColor: c.borderSoft, color: c.text, fontFamily: fonts.body }]}
        />
        <FlatList
          data={rows}
          keyExtractor={(r) => ('heading' in r ? `h-${r.heading}` : r.name)}
          keyboardShouldPersistTaps="handled"
          renderItem={({ item }) =>
            'heading' in item ? (
              <T size={12} bold style={{ color: c.gold, letterSpacing: 1, marginTop: 14, marginBottom: 4 }}>{item.heading.toUpperCase()}</T>
            ) : (
              <Pressable
                onPress={() => {
                  onPick(item.name);
                  setQ('');
                }}
                style={({ pressed }) => [st.item, { borderBottomColor: c.borderSoft, opacity: pressed ? 0.6 : 1 }]}
              >
                <T>{item.name}</T>
                {item.parent ? <T size={12} muted>{item.parent} variation</T> : null}
              </Pressable>
            )
          }
        />
        <Button title="Cancel" kind="secondary" onPress={onClose} style={{ marginTop: 8 }} />
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  sheet: { flex: 1, padding: 16, paddingTop: 24 },
  search: { borderWidth: 1, borderRadius: 5, paddingHorizontal: 10, paddingVertical: 9, fontSize: 16, marginVertical: 10 },
  item: { paddingVertical: 11, borderBottomWidth: 1 },
});
