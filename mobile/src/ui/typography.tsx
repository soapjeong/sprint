import React from 'react';
import {
  Text as RNText,
  TextInput as RNTextInput,
  type TextInputProps,
  type TextProps,
} from 'react-native';
import { font } from '@/theme';

/**
 * 앱 전체 글씨체 — 둥글둥글한 한글 서체(주아체) 하나로 통일한다.
 * react-native 의 Text/TextInput 대신 이 두 개를 쓰면 화면마다 지정할 필요가 없다.
 */
export function Text({ style, ...props }: TextProps) {
  return <RNText {...props} style={[{ fontFamily: font.family }, style]} />;
}

export function TextInput({ style, ...props }: TextInputProps) {
  return <RNTextInput {...props} style={[{ fontFamily: font.family }, style]} />;
}
