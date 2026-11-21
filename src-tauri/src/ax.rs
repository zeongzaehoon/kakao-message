//! Owned CoreFoundation/AX references. All calls stay on the automation worker.
use crate::core::Result;
use std::{
    ffi::{c_char, c_void, CString},
    ptr,
};
type Ref = *const c_void;
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    pub fn AXIsProcessTrusted() -> bool;
    fn AXUIElementCreateApplication(pid: i32) -> Ref;
    fn AXUIElementCreateSystemWide() -> Ref;
    fn AXUIElementSetMessagingTimeout(element: Ref, timeout: f32) -> i32;
    fn AXUIElementCopyAttributeValue(element: Ref, attribute: Ref, out: *mut Ref) -> i32;
    fn AXUIElementCopyMultipleAttributeValues(
        element: Ref,
        attributes: Ref,
        options: u32,
        out: *mut Ref,
    ) -> i32;
    fn AXUIElementGetAttributeValueCount(element: Ref, attribute: Ref, out: *mut isize) -> i32;
    fn AXUIElementCopyAttributeValues(
        element: Ref,
        attribute: Ref,
        index: isize,
        count: isize,
        out: *mut Ref,
    ) -> i32;
    fn AXUIElementSetAttributeValue(element: Ref, attribute: Ref, value: Ref) -> i32;
    fn AXUIElementIsAttributeSettable(element: Ref, attribute: Ref, value: *mut bool) -> i32;
    fn AXUIElementCopyActionNames(element: Ref, out: *mut Ref) -> i32;
    fn AXUIElementCopyAttributeNames(element: Ref, out: *mut Ref) -> i32;
    fn AXUIElementPerformAction(element: Ref, action: Ref) -> i32;
}
#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFRetain(value: Ref) -> Ref;
    fn CFRelease(value: Ref);
    fn CFEqual(a: Ref, b: Ref) -> bool;
    fn CFHash(value: Ref) -> usize;
    fn CFGetTypeID(value: Ref) -> usize;
    fn CFURLGetTypeID() -> usize;
    fn CFURLGetString(value: Ref) -> Ref;
    fn CFStringGetTypeID() -> usize;
    fn CFArrayGetTypeID() -> usize;
    fn CFBooleanGetTypeID() -> usize;
    fn CFBooleanGetValue(value: Ref) -> bool;
    fn CFNumberGetTypeID() -> usize;
    fn CFNumberGetValue(value: Ref, kind: isize, out: *mut c_void) -> bool;
    fn CFStringCreateWithCString(alloc: Ref, text: *const c_char, encoding: u32) -> Ref;
    fn CFStringGetLength(value: Ref) -> isize;
    fn CFStringGetCString(value: Ref, buffer: *mut c_char, size: isize, encoding: u32) -> bool;
    fn CFArrayCreate(alloc: Ref, values: *const Ref, count: isize, callbacks: Ref) -> Ref;
    fn CFArrayGetCount(value: Ref) -> isize;
    fn CFArrayGetValueAtIndex(value: Ref, index: isize) -> Ref;
    static kCFTypeArrayCallBacks: c_void;
    static kCFBooleanTrue: Ref;
}
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGEventCreateKeyboardEvent(source: Ref, key: u16, down: bool) -> Ref;
    fn CGEventSetFlags(event: Ref, flags: u64);
    fn CGEventPost(tap: u32, event: Ref);
}
#[derive(Debug)]
pub struct Cf(Ref);
impl Clone for Cf {
    fn clone(&self) -> Self {
        Self(unsafe { CFRetain(self.0) })
    }
}
impl Drop for Cf {
    fn drop(&mut self) {
        unsafe { CFRelease(self.0) }
    }
}
impl PartialEq for Cf {
    fn eq(&self, other: &Self) -> bool {
        unsafe { CFEqual(self.0, other.0) }
    }
}
impl Cf {
    unsafe fn owned(value: Ref) -> Result<Self> {
        if value.is_null() {
            Err("macOS 객체를 생성하지 못했습니다.".into())
        } else {
            Ok(Self(value))
        }
    }
    pub fn string(s: &str) -> Result<Self> {
        let s = CString::new(s).map_err(|_| "문자열에 NUL 문자가 포함됐습니다.")?;
        unsafe {
            Self::owned(CFStringCreateWithCString(
                ptr::null(),
                s.as_ptr(),
                0x08000100,
            ))
        }
    }
    pub fn array(values: &[Cf]) -> Result<Self> {
        let refs: Vec<_> = values.iter().map(|v| v.0).collect();
        unsafe {
            Self::owned(CFArrayCreate(
                ptr::null(),
                refs.as_ptr(),
                refs.len() as isize,
                &kCFTypeArrayCallBacks,
            ))
        }
    }
    pub fn text(&self) -> Option<String> {
        unsafe {
            if CFGetTypeID(self.0) != CFStringGetTypeID() {
                return None;
            }
            let mut buf = vec![0u8; (CFStringGetLength(self.0) as usize) * 4 + 1];
            if !CFStringGetCString(
                self.0,
                buf.as_mut_ptr().cast(),
                buf.len() as isize,
                0x08000100,
            ) {
                return None;
            }
            let end = buf.iter().position(|b| *b == 0)?;
            String::from_utf8(buf[..end].to_vec()).ok()
        }
    }
    pub fn items(&self) -> Vec<Self> {
        unsafe {
            if CFGetTypeID(self.0) != CFArrayGetTypeID() {
                return vec![];
            }
            (0..CFArrayGetCount(self.0))
                .map(|i| Self(CFRetain(CFArrayGetValueAtIndex(self.0, i))))
                .collect()
        }
    }
    pub fn boolean(&self) -> Option<bool> {
        unsafe { (CFGetTypeID(self.0) == CFBooleanGetTypeID()).then(|| CFBooleanGetValue(self.0)) }
    }
    pub fn number(&self) -> Option<i64> {
        unsafe {
            let mut out = 0i64;
            if CFGetTypeID(self.0) == CFNumberGetTypeID()
                && CFNumberGetValue(self.0, 4, (&mut out as *mut i64).cast())
            {
                Some(out)
            } else {
                None
            }
        }
    }
    pub fn hash(&self) -> usize {
        unsafe { CFHash(self.0) }
    }
    pub fn identifier_value(&self) -> Option<String> {
        if let Some(text) = self.text() {
            return Some(text);
        }
        if let Some(number) = self.number() {
            return Some(number.to_string());
        }
        unsafe {
            if CFGetTypeID(self.0) == CFURLGetTypeID() {
                let text = CFURLGetString(self.0);
                if !text.is_null() {
                    return Self(CFRetain(text)).text();
                }
            }
        }
        None
    }
    pub fn attribute_names(&self) -> Result<Vec<String>> {
        let mut out = ptr::null();
        let code = unsafe { AXUIElementCopyAttributeNames(self.0, &mut out) };
        if code != 0 {
            return Err(format!("접근성 속성 목록 읽기 실패: {code}"));
        }
        unsafe {
            Ok(Self::owned(out)?
                .items()
                .iter()
                .filter_map(Self::text)
                .collect())
        }
    }
    pub fn app(pid: i32) -> Result<Self> {
        unsafe {
            let system = Self::owned(AXUIElementCreateSystemWide())?;
            AXUIElementSetMessagingTimeout(system.0, 2.0);
            let app = Self::owned(AXUIElementCreateApplication(pid))?;
            AXUIElementSetMessagingTimeout(app.0, 2.0);
            Ok(app)
        }
    }
    pub fn attr(&self, name: &str) -> Result<Option<Self>> {
        let a = Self::string(name)?;
        let mut out = ptr::null();
        let code = unsafe { AXUIElementCopyAttributeValue(self.0, a.0, &mut out) };
        match code {
            0 => {
                if out.is_null() {
                    Ok(None)
                } else {
                    unsafe { Self::owned(out).map(Some) }
                }
            }
            -25205 | -25212 => Ok(None),
            _ => Err(format!("접근성 읽기 실패 ({name}): {code}")),
        }
    }
    pub fn label(&self, name: &str) -> String {
        self.attr(name)
            .ok()
            .flatten()
            .and_then(|v| v.text())
            .unwrap_or_default()
    }
    pub fn elements(&self, name: &str) -> Result<Vec<Self>> {
        Ok(self.attr(name)?.map(|v| v.items()).unwrap_or_default())
    }
    pub fn count(&self, name: &str) -> Result<Option<usize>> {
        let a = Self::string(name)?;
        let mut n = 0;
        let code = unsafe { AXUIElementGetAttributeValueCount(self.0, a.0, &mut n) };
        match code {
            0 if n >= 0 => Ok(Some(n as usize)),
            -25205 | -25212 => Ok(None),
            _ => Err(format!("목록 개수 읽기 실패: {code}")),
        }
    }
    pub fn page(&self, name: &str, start: usize, size: usize) -> Result<Vec<Self>> {
        let a = Self::string(name)?;
        let mut out = ptr::null();
        let code = unsafe {
            AXUIElementCopyAttributeValues(self.0, a.0, start as isize, size as isize, &mut out)
        };
        if code != 0 {
            return Err(format!("목록 페이지 읽기 실패: {code}"));
        }
        unsafe { Ok(Self::owned(out)?.items()) }
    }
    pub fn set(&self, name: &str, value: &Self) -> Result<()> {
        let a = Self::string(name)?;
        let code = unsafe { AXUIElementSetAttributeValue(self.0, a.0, value.0) };
        if code == 0 {
            Ok(())
        } else {
            Err(format!("접근성 설정 실패 ({name}): {code}"))
        }
    }
    pub fn focus(&self) -> Result<()> {
        self.set_true("AXFocused")
    }
    pub fn set_true(&self, attribute: &str) -> Result<()> {
        let value = unsafe { Self(CFRetain(kCFBooleanTrue)) };
        self.set(attribute, &value)
    }
    pub fn writable(&self, name: &str) -> bool {
        let Ok(a) = Self::string(name) else {
            return false;
        };
        let mut value = false;
        unsafe { AXUIElementIsAttributeSettable(self.0, a.0, &mut value) == 0 && value }
    }
    pub fn can_press(&self) -> bool {
        let mut out = ptr::null();
        let code = unsafe { AXUIElementCopyActionNames(self.0, &mut out) };
        if code != 0 || out.is_null() {
            return false;
        }
        unsafe {
            Self::owned(out)
                .map(|v| {
                    v.items()
                        .iter()
                        .any(|x| x.text().as_deref() == Some("AXPress"))
                })
                .unwrap_or(false)
        }
    }
    pub fn action(&self, name: &str) -> Result<()> {
        let a = Self::string(name)?;
        let code = unsafe { AXUIElementPerformAction(self.0, a.0) };
        if code == 0 {
            Ok(())
        } else {
            Err(format!("{name} 결과 확인 필요: {code}"))
        }
    }
    pub fn metadata(&self) -> Result<Vec<String>> {
        let names = ["AXRole", "AXTitle", "AXDescription", "AXIdentifier"]
            .iter()
            .map(|s| Self::string(s))
            .collect::<Result<Vec<_>>>()?;
        let attrs = Self::array(&names)?;
        let mut out = ptr::null();
        let code = unsafe { AXUIElementCopyMultipleAttributeValues(self.0, attrs.0, 0, &mut out) };
        if code != 0 {
            return Err(format!("화면 요소 읽기 실패: {code}"));
        }
        let values = unsafe { Self::owned(out)? }.items();
        if values.len() != 4 {
            return Err("화면 요소 정보가 불완전합니다.".into());
        }
        Ok(values
            .iter()
            .map(|v| v.text().unwrap_or_default())
            .collect())
    }
}
pub fn key(key: u16, command: bool) -> Result<()> {
    unsafe {
        let down = Cf::owned(CGEventCreateKeyboardEvent(ptr::null(), key, true))?;
        let up = Cf::owned(CGEventCreateKeyboardEvent(ptr::null(), key, false))?;
        for event in [&down, &up] {
            CGEventSetFlags(event.0, if command { 1 << 20 } else { 0 });
            CGEventPost(0, event.0);
        }
        Ok(())
    }
}
#[derive(Clone, Debug)]
pub struct Node {
    pub ax: Cf,
    pub role: String,
    pub name: String,
    pub id: String,
}
impl Node {
    pub fn read(ax: Cf) -> Result<Self> {
        let v = ax.metadata()?;
        let name = if !v[1].is_empty() {
            v[1].clone()
        } else if !v[2].is_empty() {
            v[2].clone()
        } else if v[0] == "AXStaticText" {
            ax.label("AXValue")
        } else {
            String::new()
        };
        Ok(Self {
            ax,
            role: v[0].clone(),
            name: crate::core::canonical(&name),
            id: v[3].clone(),
        })
    }
    pub fn children(&self) -> Result<Vec<Self>> {
        self.ax
            .elements("AXChildren")?
            .into_iter()
            .map(Self::read)
            .collect()
    }
    pub fn direct(&self, role: &str, id: &str, name: &str) -> Result<Self> {
        let mut last = String::new();
        for _ in 0..3 {
            match self.children() {
                Ok(children) => {
                    let found: Vec<_> = children
                        .into_iter()
                        .filter(|n| {
                            (role.is_empty() || n.role == role)
                                && (id.is_empty() || n.id == id)
                                && (name.is_empty() || n.name == name)
                        })
                        .collect();
                    if found.len() == 1 {
                        return Ok(found.into_iter().next().unwrap());
                    }
                    return Err(format!(
                        "화면 요소 식별 실패 (role={role}, id={id}, 일치 {}개)",
                        found.len()
                    ));
                }
                Err(e) => {
                    if !e.contains("-25202") {
                        return Err(e);
                    }
                    last = e;
                    std::thread::sleep(std::time::Duration::from_millis(50));
                }
            }
        }
        Err(last)
    }
    pub fn enabled(&self) -> bool {
        self.ax
            .attr("AXEnabled")
            .ok()
            .flatten()
            .and_then(|v| v.boolean())
            == Some(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn cf_unicode_and_array_ownership() {
        let text = Cf::string("한국어 👋").unwrap();
        let array = Cf::array(std::slice::from_ref(&text)).unwrap();
        drop(text);
        let values = array.items();
        drop(array);
        assert_eq!(values[0].text().as_deref(), Some("한국어 👋"));
    }
    #[test]
    fn non_string_metadata_is_not_formatted_as_a_title() {
        let array = Cf::array(&[]).unwrap();
        assert_eq!(array.text(), None);
        assert_eq!(array.number(), None);
        assert_eq!(array.boolean(), None);
    }
    #[test]
    fn nul_is_rejected() {
        assert!(Cf::string("hello\0world").is_err());
    }
}
