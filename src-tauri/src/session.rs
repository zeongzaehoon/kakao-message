use crate::core::*;
use std::{
    sync::{atomic::Ordering, mpsc},
    thread,
};

pub enum Event {
    Catalog(Catalog),
    Invalidated,
    Progress(usize, usize),
    Outcome(Outcome),
    Photos(Vec<Photo>),
    Done(Result<()>),
}
enum Command {
    Load(Stop),
    Send(Box<Plan>, Stop),
}

#[cfg(any(target_os = "macos", test))]
pub trait CatalogBackend: Backend {
    fn pid(&self) -> i32;
    fn alive(&self) -> bool;
    fn catalog(&mut self, stop: &Stop, progress: &mut dyn FnMut(usize, usize)) -> Result<Catalog>;
}
#[cfg(any(target_os = "macos", test))]
struct Session<D> {
    driver: Option<D>,
}
#[cfg(any(target_os = "macos", test))]
impl<D: CatalogBackend> Session<D> {
    fn load(
        &mut self,
        connect: impl FnOnce() -> Result<D>,
        stop: &Stop,
        progress: &mut dyn FnMut(usize, usize),
    ) -> Result<Catalog> {
        let result = (|| {
            if self.driver.as_ref().is_none_or(|d| !d.alive()) {
                self.driver = Some(connect()?);
            }
            self.driver.as_mut().unwrap().catalog(stop, progress)
        })();
        if result.is_err() {
            self.driver = None;
        }
        result
    }
    fn send(
        &mut self,
        plan: &Plan,
        journal: &Journal,
        stop: &Stop,
        report: impl FnMut(Outcome),
    ) -> Result<()> {
        let driver = self
            .driver
            .as_mut()
            .ok_or("목록 연결이 없습니다. 새로고침하고 대화방을 선택하세요.")?;
        if !driver.alive() || driver.pid() != plan.pid {
            return Err(
                "목록 조회 후 카카오톡 연결이 바뀌었습니다. 새로고침하고 다시 선택하세요.".into(),
            );
        }
        driver.validate_selection(&plan.rooms)?;
        execute(plan, driver, journal, stop, report)
    }
}

/// AX objects are created, retained, used and released on this one worker.
/// UI messages carry opaque keys, not pointers or accessibility objects.
pub struct Worker {
    tx: Option<mpsc::Sender<Command>>,
    thread: Option<thread::JoinHandle<()>>,
    active_stop: std::sync::Arc<std::sync::Mutex<Stop>>,
    closing: Stop,
}
impl Worker {
    pub fn new(events: mpsc::Sender<Event>) -> Self {
        let (tx, rx) = mpsc::channel();
        let active_stop = std::sync::Arc::new(std::sync::Mutex::new(Stop::default()));
        let worker_stop = active_stop.clone();
        let closing = Stop::default();
        let worker_closing = closing.clone();
        let thread = thread::spawn(move || {
            #[cfg(target_os = "macos")]
            let mut session = Session { driver: None };
            while let Ok(command) = rx.recv() {
                let stop = match &command {
                    Command::Load(stop) | Command::Send(_, stop) => stop.clone(),
                };
                if let Ok(mut current) = worker_stop.lock() {
                    *current = stop;
                }
                if worker_closing.load(Ordering::Relaxed) {
                    break;
                }
                let loading = matches!(&command, Command::Load(_));
                let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    #[cfg(target_os = "macos")]
                    {
                        objc2::rc::autoreleasepool(|_| match command {
                            Command::Load(stop) => {
                                let catalog = session.load(
                                    || crate::native::Native::connect(None),
                                    &stop,
                                    &mut |i, n| {
                                        let _ = events.send(Event::Progress(i, n));
                                    },
                                )?;
                                events
                                    .send(Event::Catalog(catalog))
                                    .map_err(|e| e.to_string())
                            }
                            Command::Send(plan, stop) => {
                                let journal = Journal::open(&data_dir().join("attempts.sqlite3"))?;
                                session.send(&plan, &journal, &stop, |outcome| {
                                    let _ = events.send(Event::Outcome(outcome));
                                })
                            }
                        })
                    }
                    #[cfg(not(target_os = "macos"))]
                    {
                        if let Command::Send(plan, _) = command {
                            let _ = plan.pid;
                        }
                        Err("Windows 카카오톡 전송은 아직 지원하지 않습니다.".into())
                    }
                }));
                let result = match result {
                    Ok(result) => result,
                    Err(_) => {
                        #[cfg(target_os = "macos")]
                        {
                            session.driver = None;
                        }
                        let _ = events.send(Event::Invalidated);
                        Err("연결 작업 중 내부 오류가 발생했습니다. 전송 결과를 확인하고 목록을 새로고침하세요.".into())
                    }
                };
                if loading && result.is_err() {
                    let _ = events.send(Event::Invalidated);
                }
                if events.send(Event::Done(result)).is_err() {
                    break;
                }
            }
        });
        Self {
            tx: Some(tx),
            thread: Some(thread),
            active_stop,
            closing,
        }
    }
    pub fn load(&self, stop: Stop) -> Result<()> {
        self.tx
            .as_ref()
            .ok_or("연결 작업이 종료됐습니다.")?
            .send(Command::Load(stop))
            .map_err(|e| e.to_string())
    }
    pub fn send(&self, plan: Plan, stop: Stop) -> Result<()> {
        self.tx
            .as_ref()
            .ok_or("연결 작업이 종료됐습니다.")?
            .send(Command::Send(Box::new(plan), stop))
            .map_err(|e| e.to_string())
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        self.closing.store(true, Ordering::Relaxed);
        if let Ok(stop) = self.active_stop.lock() {
            stop.store(true, Ordering::Relaxed);
        }
        self.tx.take();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        path::Path,
        sync::{atomic::AtomicUsize, Arc},
    };
    struct Fake {
        lists: Arc<AtomicUsize>,
        sends: usize,
        fail_load: bool,
        alive: bool,
    }
    impl Backend for Fake {
        fn prepare(&mut self, _: &Room, _: &Stop) -> Result<()> {
            Ok(())
        }
        fn text(&mut self, _: &Room, _: &str, _: &Stop) -> Result<()> {
            self.sends += 1;
            Ok(())
        }
        fn photo(&mut self, _: &Room, _: &Photo, _: &Stop) -> Result<()> {
            Ok(())
        }
        fn finish(&mut self, _: &Room, _: &Stop) -> Result<()> {
            Ok(())
        }
    }
    impl CatalogBackend for Fake {
        fn pid(&self) -> i32 {
            123
        }
        fn alive(&self) -> bool {
            self.alive
        }
        fn catalog(&mut self, _: &Stop, _: &mut dyn FnMut(usize, usize)) -> Result<Catalog> {
            self.lists.fetch_add(1, Ordering::Relaxed);
            if self.fail_load {
                return Err("load failed".into());
            }
            Ok(Catalog {
                pid: 123,
                rooms: vec![],
                complete: true,
                note: String::new(),
            })
        }
    }
    fn fake(lists: Arc<AtomicUsize>) -> Fake {
        Fake {
            lists,
            sends: 0,
            fail_load: false,
            alive: true,
        }
    }
    fn plan() -> Plan {
        Plan {
            pid: 123,
            rooms: vec![Room {
                key: "key".into(),
                name: "room".into(),
                selectable: true,
                note: String::new(),
            }],
            message: "test".into(),
            photos: vec![],
            live: true,
            interval: 0.,
        }
    }
    #[test]
    fn load_then_send_uses_same_driver_without_second_list_or_connection() {
        let lists = Arc::new(AtomicUsize::new(0));
        let mut session = Session { driver: None };
        session
            .load(|| Ok(fake(lists.clone())), &Stop::default(), &mut |_, _| {})
            .unwrap();
        session
            .send(
                &plan(),
                &Journal::open(Path::new(":memory:")).unwrap(),
                &Stop::default(),
                |_| {},
            )
            .unwrap();
        assert_eq!(lists.load(Ordering::Relaxed), 1);
        assert_eq!(session.driver.as_ref().unwrap().sends, 1);
        session
            .load(
                || panic!("must reuse live driver"),
                &Stop::default(),
                &mut |_, _| {},
            )
            .unwrap();
    }
    #[test]
    fn failed_refresh_invalidates_old_session() {
        let mut session = Session {
            driver: Some(fake(Arc::default())),
        };
        session.driver.as_mut().unwrap().fail_load = true;
        assert!(session
            .load(|| panic!("must reuse"), &Stop::default(), &mut |_, _| {})
            .is_err());
        assert!(session.driver.is_none());
        assert!(session
            .send(
                &plan(),
                &Journal::open(Path::new(":memory:")).unwrap(),
                &Stop::default(),
                |_| {}
            )
            .is_err());
    }
    #[test]
    fn restarted_process_cannot_receive_a_previously_selected_plan() {
        let mut session = Session {
            driver: Some(fake(Arc::default())),
        };
        session.driver.as_mut().unwrap().alive = false;
        assert!(session
            .send(
                &plan(),
                &Journal::open(Path::new(":memory:")).unwrap(),
                &Stop::default(),
                |_| {}
            )
            .is_err());
        assert_eq!(session.driver.as_ref().unwrap().sends, 0);
    }
}
